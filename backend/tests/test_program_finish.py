"""飾り・画像インサート・曲まで通しで作る（backend/program_package/finish.py）と、その部品のつなぎ目。

本物の書き出し（42 分）は検査の場では流さない。つなぎ目（承認済みの案だけが飾りに入る、
曲の台帳から音の指定ができる、確かめと控えが残る）を、作った絵と作った音で確かめる。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from backend.program_package import episode as ep
from backend.program_package import finish as fin
from backend.program_package import inserts as ins
from backend.program_package import music as mu
from backend.program_package import opening
from backend.tests.test_program_inserts import CAPS, SETUP, the_map
from backend.tests.test_program_music import song

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg が無い")
ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "backend" / "config" / "episode" / "20250922_久木田ヒロノブ.json"
PROGRAM = ROOT / "backend" / "config" / "program" / "美麗の書道対談.json"


def video(path, seconds, size="640x360"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s={size}:r=10:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=f=300:r=48000:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


@pytest.fixture
def plan_file(tmp_path):
    plan = ins.propose({}, CAPS, the_map(), SETUP)
    plan["setup"] = SETUP
    path = tmp_path / "inserts.json"
    ins.save_plan(path, plan)
    return path


def test_未承認の案は飾りに入らない(tmp_path, plan_file):
    src = video(tmp_path / "v62.mp4", 80)
    assert ep._inserts({"recording": "x", "inserts": str(plan_file)}, src, tmp_path) == []


def test_承認した案だけが飾りと同じ形で入る(tmp_path, plan_file):
    src = video(tmp_path / "v62.mp4", 80)
    plan = ins.load_plan(plan_file)
    ins.decide(plan, ["i01"], ins.APPROVED, by="北原", evidence="チャット", people=["北原"])
    ins.save_plan(plan_file, plan)
    got = ep._inserts({"recording": "x", "inserts": str(plan_file)}, src, tmp_path)
    assert [(at, sec) for _, at, sec in got] == [(70, 5.0)]
    assert Image.open(got[0][0]).size == (1280, 720)
    assert ep._inserts({"recording": "x", "inserts": False}, src, tmp_path) == []


def test_案の置き場が無い回は何も入らない(tmp_path):
    assert ep._inserts({"recording": "まだ無い回"}, tmp_path / "x.mp4", tmp_path) == []


def ledger(**over):
    led = {"tracks": {"a": {"title": "A", "artist": "x", "source": "自作", "file": "a.wav"},
                      "b": {"title": "B", "artist": "y", "source": "OpenTracks", "file": "b.wav"}},
           "programs": {"美麗の書道対談": {"op": {"track": "a", "volume": 0.9, "start": None},
                                     "bgm": {"track": "b", "volume_db": -22, "fade": 3.0},
                                     "ed": {"track": "a", "volume": 0.7, "fade_out": 5.5}}}, "peak_db": -1.5}
    led.update(over)
    return led


@pytest.fixture
def songs(tmp_path):
    song(tmp_path / "a.wav")
    song(tmp_path / "b.wav", seconds=30, loud=())
    return tmp_path


def test_曲の台帳から音の指定を作りOPの使い始めは山に合わせる(songs):
    a = mu.plan(opening.load(PROGRAM), ledger(), songs)
    assert a["op_music"]["start"] == pytest.approx(19.5, abs=0.1) and a["op_music"]["path"].endswith("a.wav")
    assert a["bgm"]["volume_db"] == -22 and "ranges" not in a["bgm"]
    assert a["ed_music"]["fade_out"] == 5.5 and a["tracks"]["bgm"]["source"] == "OpenTracks"


def test_台帳で決めた使い始めはそのまま使う(songs):
    led = ledger()
    led["programs"]["美麗の書道対談"]["op"]["start"] = 3.0
    assert mu.plan(opening.load(PROGRAM), led, songs)["op_music"]["start"] == 3.0


@pytest.mark.parametrize("change,word", [({"source": ""}, "出どころ"), ({"file": None}, "決まっていません"),
                                         ({"file": "無い.wav"}, "ありません")])
def test_出どころやファイルの無い曲では止まる(songs, change, word):
    led = ledger()
    led["tracks"]["b"].update(change)
    with pytest.raises(mu.MusicError, match=word):
        mu.plan(opening.load(PROGRAM), led, songs)


def test_曲を止める区間を避けてBGMを敷く():
    assert mu.bgm_ranges(2558.0, [[1790.0, 1834.0]]) == [[0.0, 1790.0], [1834.0, 2558.0]]
    assert mu.bgm_ranges(100.0, [[0.0, 5.0], [95.0, 100.0]]) == [[5.0, 95.0]]
    assert mu.bgm_ranges(100.0, [[3.0, 99.0]]) == []  # 短い切れ端には敷かない


def test_本物の台帳は読めて出どころが書いてある():
    led = json.loads(mu.LEDGER.read_text(encoding="utf-8"))
    use = led["programs"]["美麗の書道対談"]
    for role in ("op", "bgm", "ed"):
        assert led["tracks"][use[role]["track"]]["source"].strip()


def test_通しで作ると曲が入り確かめと控えが残る(tmp_path, songs, monkeypatch):
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec.update(source=str(video(tmp_path / "v62.mp4", 30)), inserts=False,
                package=str(ROOT / spec["package"]), program=str(PROGRAM))
    total = ep.op_length(spec) + 30 + spec["ending"]["seconds"]

    def fake_build(s, out, cards_only=False):  # 飾りの書き出し（8 分）の代わりに、同じ長さの絵を置く
        assert ep.program_of(s)["music"] is None  # OP の曲は remix が入れるので、番組 OP は無音で作る
        out.mkdir(parents=True, exist_ok=True)
        return video(out / f"{s['recording']}_{s['version']}.mp4", total)

    monkeypatch.setattr(ep, "build", fake_build)
    monkeypatch.setattr(mu, "LEDGER", tmp_path / "music.json")
    (tmp_path / "music.json").write_text(json.dumps(ledger(), ensure_ascii=False), encoding="utf-8")
    note = fin.finish(spec, tmp_path / "out", "v99", music_dir=str(songs))
    final = tmp_path / "out" / note["file"]
    assert final.exists() and abs(mu.read(final).size / mu.SR - total) < 0.5
    checks = {c["id"]: c for c in note["checks"]}
    assert checks["op_climax"]["ok"], checks["op_climax"]
    assert "quality" in checks and note["state"].startswith("承認待ち")
    assert [s["step"] for s in note["steps"]] == ["飾り", "曲"]
    assert (tmp_path / "out" / "20250922_久木田ヒロノブ_v99_仕上げの控え.json").exists()


def test_曲のファイルが決まっていなければ書き出す前に止まる(tmp_path, monkeypatch):
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec.update(source=str(video(tmp_path / "v62.mp4", 5)), inserts=False,
                package=str(ROOT / spec["package"]), program=str(PROGRAM))
    monkeypatch.setattr(ep, "build", lambda *a, **k: pytest.fail("書き出しまで進んだ"))
    with pytest.raises(mu.MusicError, match="決まっていません"):
        fin.finish(spec, tmp_path / "out", "v99", music_dir=str(tmp_path))
