"""曲を聞いて番組 OP の使い始めを決める（backend/program_package/music.py）。

曲そのものはリポジトリに置かないので、作った音（拍と、途中から大きくなる山）で確かめる。
"""
import re
import shutil
import subprocess
import sys
import types
import wave
from pathlib import Path

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


# ════ 本線（render_worker）が曲の台帳の BGM を混ぜる ════
# 本線（render_worker）が曲の台帳の BGM を混ぜる（2026-11-14）。
#
# これまで本線は `branding/bgm/default_bgm.mp3` しか見ず、曲が置かれていないので
# 毎回 `BGMミキシング(ファイルなし)` を記録に出していた（feature_gaps の bgm_mixing）。
# 曲の台帳（backend/config/music.json）と remix の音の組み立てを本線からも使う。
#
# 曲そのものはリポジトリに置かないので、作った音で確かめる:
# 話し声の代わりは 300Hz（鳴る・止まるを繰り返す）、曲の代わりは 2000Hz（鳴りっぱなし）。
#
# 別のファイルにしないのは、pytest.ini の testpaths に 1 行足すと束の区切りがずれて、
# 前からあるテストどうしの汚染（test_render_router → test_settings_manager）が出るため（2026-11-14 CI で実測）

LEDGER = {
    "tracks": {
        "op": {"title": "OPの曲", "source": "テスト", "file": "op.mp3"},
        "bed": {"title": "下に敷く曲", "artist": "テスト", "source": "テストで作った音", "file": "bed.m4a"},
    },
    "programs": {"番組": {
        "op": {"track": "op", "volume": 0.9, "start": None},
        "bgm": {"track": "bed", "volume_db": -22, "duck": True, "duck_ratio": 3, "fade": 3.0},
    }},
    "mainline": {"program": "番組"},
    "peak_db": -1.5,
}


def _ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True, timeout=120)


def level(path, a, b, band):
    """a〜b 秒の、band(Hz) の辺りだけの音の大きさ（dBFS の RMS）。"""
    f = f"atrim={a}:{b},bandpass=f={band}:w=60,astats=metadata=0"
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-af", f, "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    m = re.findall(r"RMS level dB: (-?[\d.]+|-inf)", r.stderr)[-1]
    return -200.0 if m == "-inf" else float(m)


@pytest.fixture
def music_dir(tmp_path):
    d = tmp_path / "music"
    d.mkdir()
    _ff("-f", "lavfi", "-i", "aevalsrc=0.8*sin(2*PI*2000*t):s=48000", "-t", "9", "-c:a", "aac", str(d / "bed.m4a"))
    return d


@pytest.fixture
def video(tmp_path):
    """24 秒。話し声の代わり（300Hz）が 8〜16 秒だけ鳴る。前後は無音。"""
    p = tmp_path / "final.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=10", "-f", "lavfi",
        "-i", "aevalsrc='if(gte(t,8)*lt(t,16),0.5*sin(2*PI*300*t),0)':s=48000:c=stereo",
        "-t", "24", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p))
    return p


class _Ctx:
    def __init__(self):
        self.skipped_features = []
        self.render_bgm = None


@pytest.fixture
def worker(monkeypatch):
    """本物の ffmpeg を呼ぶ RenderWorker。テンプレートと既定の曲は無い状態にする。"""
    backend = str(Path(__file__).resolve().parents[1])
    if backend not in sys.path:
        monkeypatch.syspath_prepend(backend)
    from agents.workers import render_worker as rw

    class _FF:
        def is_available(self):
            return True

        def run_command(self, args, timeout=600):
            r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", *args], capture_output=True, text=True,
                               timeout=timeout, check=False)
            return r.returncode == 0, r.stderr

    ve = types.ModuleType("video_editor_engine")
    ve.video_editor = types.SimpleNamespace(ffmpeg=_FF())
    tc = types.ModuleType("template_config")
    tc.template_config = types.SimpleNamespace(is_active=False)
    monkeypatch.setitem(sys.modules, "video_editor_engine", ve)
    monkeypatch.setitem(sys.modules, "template_config", tc)
    monkeypatch.setattr(rw, "DEFAULT_BGM", Path("/nonexistent/default_bgm.mp3"))
    monkeypatch.setattr(mu, "load_ledger", lambda: LEDGER)
    monkeypatch.delenv("AVS_MUSIC_DIR", raising=False)
    return rw.RenderWorker()


# ── 曲の台帳から本線の BGM を引く ──────────────────────────────

def test_本線のBGMは台帳の番組のBGMだけを引く_OPの曲が無くても止まらない(music_dir):
    spec = mu.mainline_bgm(LEDGER, music_dir)
    assert spec["op_music"] is None and spec["ed_music"] is None
    assert spec["bgm"]["path"] == str(music_dir / "bed.m4a")
    assert spec["bgm"]["volume_db"] == -22 and spec["bgm"]["duck_ratio"] == 3
    assert spec["tracks"]["bgm"]["title"] == "下に敷く曲"


def test_曲の置き場が無ければ理由を言って止まる():
    with pytest.raises(mu.MusicError, match="曲の置き場"):
        mu.mainline_bgm(LEDGER, None)


def test_曲のファイルが無ければ理由を言って止まる(tmp_path):
    with pytest.raises(mu.MusicError, match="曲のファイルがありません"):
        mu.mainline_bgm(LEDGER, tmp_path)


def test_台帳に本線の番組が書いていなければ理由を言って止まる(music_dir):
    with pytest.raises(mu.MusicError, match="本線"):
        mu.mainline_bgm({**LEDGER, "mainline": {}}, music_dir)


def test_出どころの無い曲は本線でも使わない(music_dir):
    led = {**LEDGER, "tracks": {**LEDGER["tracks"], "bed": {"title": "x", "source": "", "file": "bed.m4a"}}}
    with pytest.raises(mu.MusicError, match="出どころ"):
        mu.mainline_bgm(led, music_dir)


def test_本物の台帳には本線の番組が書いてある():
    led = mu.load_ledger()
    name = led["mainline"]["program"]
    assert led["programs"][name]["bgm"]["track"] in led["tracks"]


# ── 本線の書き出し ───────────────────────────────────────────

def test_本線は台帳の曲を混ぜ_話し声の下で曲を下げ_失敗の記録を出さない(worker, video, music_dir, monkeypatch):
    monkeypatch.setenv("AVS_MUSIC_DIR", str(music_dir))
    before_v = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                               "stream=nb_frames", "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout
    ctx = _Ctx()
    worker._mix_bgm(str(video), ctx)

    assert ctx.skipped_features == []                       # 「BGMミキシング…」が記録に出ない
    assert ctx.render_bgm["title"] == "下に敷く曲"           # 何の曲を入れたかが記録に残る
    assert ctx.render_bgm["source"] == "テストで作った音"
    assert ctx.render_bgm["from"] == "曲の台帳"
    quiet = level(video, 4, 7, 2000)      # 話していない所の曲
    under = level(video, 11, 15, 2000)    # 話している間の曲
    assert quiet > -40                    # 曲が入っている（-22dB で敷く）
    assert quiet - under >= 3             # 話し声の下で曲が下がる
    assert level(video, 20, 23, 2000) > -45   # 9 秒の曲を繰り返して最後まで敷く（終わりは下げていく）
    assert level(video, 11, 15, 300) > -12    # 話し声は小さくならない（古い作りは半分になっていた）
    after_v = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                              "stream=nb_frames", "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout
    assert after_v == before_v            # 映像は写すだけ
    assert not Path(str(video) + ".bgm.mp4").exists()


def test_曲の置き場が無いときは_これまでどおり記録に出す(worker, video):
    ctx = _Ctx()
    worker._mix_bgm(str(video), ctx)
    assert ctx.skipped_features == ["BGMミキシング(ファイルなし)"]
    assert ctx.render_bgm is None


def test_短い動画でも止まらずに混ぜる(worker, tmp_path, music_dir, monkeypatch):
    """出し入れ 3 秒×2 より短い動画（5 秒）。出し入れを縮めて混ぜる。"""
    monkeypatch.setenv("AVS_MUSIC_DIR", str(music_dir))
    p = tmp_path / "short.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=10", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", "5", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p))
    ctx = _Ctx()
    worker._mix_bgm(str(p), ctx)
    assert ctx.skipped_features == []
    assert level(p, 2, 3, 2000) > -40


def test_テンプレートの曲も同じ組み立てで混ぜる(worker, video, music_dir, monkeypatch):
    """テンプレートの bgm_path が先（これまでどおり）。混ぜ方は台帳の曲と同じ。"""
    sys.modules["template_config"].template_config = types.SimpleNamespace(
        is_active=True, get_branding_config=lambda: {"bgm_path": str(music_dir / "bed.m4a")})
    ctx = _Ctx()
    worker._mix_bgm(str(video), ctx)
    assert ctx.skipped_features == []
    assert ctx.render_bgm["from"] == "テンプレート"
    assert level(video, 4, 7, 2000) - level(video, 11, 15, 2000) >= 3


def test_混ぜるのに失敗したら記録に出し_書きかけを残さない(worker, video, music_dir, monkeypatch):
    monkeypatch.setenv("AVS_MUSIC_DIR", str(music_dir))
    (music_dir / "bed.m4a").write_bytes(b"not audio")
    ctx = _Ctx()
    worker._mix_bgm(str(video), ctx)
    assert ctx.skipped_features == ["BGMミキシング"]
    assert ctx.render_bgm is None
    assert not Path(str(video) + ".bgm.mp4").exists()


# ── 曲をクラウドの作業場に持ってくる（Drive の 20_素材/共通 から） ─────────────

def _drive(monkeypatch, files):
    """Drive の代わり。files は {フォルダ: [(名前, 中身)]}。フォルダは 20_素材/共通 と、その下の「曲」。"""
    import hashlib

    from backend import raw_source as rs
    tree = {"base": ["20_素材", "30_AVS_作業"], "20_素材": ["共通"], "共通": ["曲"], "曲": [],
            "30_AVS_作業": ["番組資産"], "番組資産": ["AIの曲"]}
    monkeypatch.setattr(mu, "DRIVE_PLACES", ("20_素材/共通", "30_AVS_作業/番組資産/AIの曲", "無い場所"))
    body = {f"{folder}/{name}": data for folder, items in files.items() for name, data in items}
    monkeypatch.setattr(rs, "list_folders", lambda s, parent: [{"id": n, "name": n} for n in tree.get(parent, [])])
    monkeypatch.setattr(rs, "_list_files", lambda s, q, fields: [
        {"id": k, "name": k.split("/", 1)[1], "md5Checksum": hashlib.md5(v).hexdigest()}
        for k, v in body.items() if q.startswith(f"'{k.split('/', 1)[0]}' in parents")])
    monkeypatch.setattr(rs, "_download", lambda s, file_id, dest: dest.write_bytes(body[file_id]))

    class _Svc:
        def files(self):
            return self

        def get(self, **kw):
            return self

        def execute(self):
            return {"parents": ["base"]}
    return _Svc()


ENV = {"AVS_RAW_DRIVE_FOLDER_ID": "raw"}


def test_置き場に無い曲だけをDriveから落とす(tmp_path, monkeypatch):
    svc = _drive(monkeypatch, {"共通": [("op.mp3", b"OP")], "曲": [("bed.m4a", b"BED"), ("other.mp3", b"X")]})
    (tmp_path / "op.mp3").write_bytes(b"already here")
    r = mu.fetch(LEDGER, tmp_path, service=svc, env=ENV)
    assert r["fetched"] == ["bed.m4a"] and r["not_found"] == []
    assert (tmp_path / "bed.m4a").read_bytes() == b"BED"
    assert (tmp_path / "op.mp3").read_bytes() == b"already here"     # ある曲は触らない
    assert not (tmp_path / "other.mp3").exists()                     # 台帳に無い曲は落とさない
    assert mu.fetch(LEDGER, tmp_path, service=svc, env=ENV)["already"] is True


def test_AIが置く場所の曲も落とす(tmp_path, monkeypatch):
    svc = _drive(monkeypatch, {"AIの曲": [("op.mp3", b"OP"), ("bed.m4a", b"BED")]})
    r = mu.fetch(LEDGER, tmp_path, service=svc, env=ENV)
    assert sorted(r["fetched"]) == ["bed.m4a", "op.mp3"]


def test_Driveに無い曲は名前を返す(tmp_path, monkeypatch):
    svc = _drive(monkeypatch, {"曲": [("bed.m4a", b"BED")]})
    r = mu.fetch(LEDGER, tmp_path, service=svc, env=ENV)
    assert r["fetched"] == ["bed.m4a"] and r["not_found"] == ["op.mp3"]


def test_同じ名前で中身の違う曲が2つあれば_決めずに止まる(tmp_path, monkeypatch):
    svc = _drive(monkeypatch, {"共通": [("bed.m4a", b"A")], "曲": [("bed.m4a", b"B")]})
    with pytest.raises(mu.MusicError, match="中身ちがい"):
        mu.fetch(LEDGER, tmp_path, service=svc, env=ENV)
    assert not (tmp_path / "bed.m4a").exists()


# ---- 好みカルテの推定と出題（taste_model・2026-11-15 設計） ----

from datetime import date as _date

from backend.program_package import taste_model as tm

_TODAY = _date(2026, 11, 15)


def _shelf(n=6):
    return [{"id": f"s{i}", "features": {"bpm": 80 + 10 * i, "brightness": 1500 + 100 * i, "density": 2 + i * .2,
                                         "steadiness": .5 + .05 * i, "dynamics_db": 10 + i}, "tags": []} for i in range(n)]


def test_answers_count_as_designed():
    idx = {"a": 0, "b": 1, "c": 2}
    assert tm.to_obs({"a": "a", "b": "b", "pick": "a"}, idx, _TODAY) == [(0, 1, 1.0)]
    both = tm.to_obs({"a": "a", "b": "b", "pick": "both"}, idx, _TODAY)
    assert (0, tm.BAR, .5) in both and (1, tm.BAR, .5) in both
    neither = tm.to_obs({"a": "a", "b": "b", "pick": "neither"}, idx, _TODAY)
    assert (tm.BAR, 0, .5) in neither and (tm.BAR, 1, .5) in neither
    dec = tm.to_obs({"pick": "decide", "song": "a", "with": ["b", "c"]}, idx, _TODAY)
    assert dec == [(0, tm.BAR, 2.0), (0, 1, 1.0), (0, 2, 1.0)]
    assert tm.to_obs({"a": "a", "b": "b", "pick": "a", "who": "ためし"}, idx, _TODAY) == []
    old = tm.to_obs({"a": "a", "b": "b", "pick": "a", "at": "2026-05-19"}, idx, _TODAY)
    assert abs(old[0][2] - 0.5) < 0.01          # 180日で半分


def test_features_are_standardised_and_clipped():
    items = _shelf()
    items.append({"id": "x", "features": {"bpm": 10_000}, "tags": ["ピアノ"]})
    z = tm.matrix(items, tm.baseline(_shelf()))
    assert z[:, :5].max() <= tm.CLIP and z[-1, 0] == tm.CLIP
    assert z[-1, len(tm.MEASURED) + tm.TAGS.index("ピアノ")] == 1.0


def test_winner_ranks_first_and_neither_says_no_favorite():
    items = _shelf(4)
    z = tm.matrix(items, tm.baseline(items))
    idx = {it["id"]: i for i, it in enumerate(items)}
    ans = [{"a": "s0", "b": "s1", "pick": "a"}, {"a": "s0", "b": "s2", "pick": "a"}, {"a": "s0", "b": "s3", "pick": "a"}]
    post = tm.fit(z, [o for a in ans for o in tm.to_obs(a, idx, _TODAY)])
    assert tm.summary(post, {0, 1, 2, 3})["ranking"][0]["id"] == "0"
    bad = [{"a": f"s{i}", "b": f"s{j}", "pick": "neither"} for i in range(4) for j in range(i + 1, 4)] * 3
    post = tm.fit(z, [o for a in bad for o in tm.to_obs(a, idx, _TODAY)])
    assert tm.summary(post, {0, 1, 2, 3})["no_favorite"]


def test_first_rounds_introduce_new_songs_then_refine():
    items = _shelf(4)
    z = tm.matrix(items, tm.baseline(items))
    post = tm.fit(z, [])
    a, b = tm.next_pair(post, [0, 1, 2, 3], set(), set())
    assert {a, b}.isdisjoint(set()) and a != b
    a2, b2 = tm.next_pair(post, [0, 1, 2, 3], {a, b}, set())
    assert {a2, b2}.isdisjoint({a, b})           # 顔見せ: まだ聞いていない2曲
    a3, b3 = tm.next_pair(post, [0, 1, 2, 3], {0, 1, 2, 3}, {(0, 1)})
    assert a3 != b3


def test_early_stop_when_top_beat_second_and_third():
    items = _shelf(4)
    z = tm.matrix(items, tm.baseline(items))
    idx = {it["id"]: i for i, it in enumerate(items)}
    ans = [("s0", "s1", "a"), ("s0", "s2", "a"), ("s1", "s3", "a"), ("s2", "s3", "a")]
    post = tm.fit(z, [o for a, b, p in ans for o in tm.to_obs({"a": a, "b": b, "pick": p}, idx, _TODAY)])
    session = [(idx[a], idx[b], p) for a, b, p in ans]
    assert not tm.early_stop(post, [0, 1, 2, 3], session, 5)
    assert tm.early_stop(post, [0, 1, 2, 3], session, 6)
    assert not tm.early_stop(post, [0, 1, 2, 3], session[1:], 6)   # 2位か3位に直接は勝っていない


def test_narrow_pack_has_anchors_near_and_far():
    rng = np.random.default_rng(0)
    z = rng.normal(size=(20, len(tm.MEASURED) + len(tm.TAGS)))
    post = tm.fit(z, [(0, 1, 1.0), (0, 2, 1.0), (3, 2, 1.0)])
    pack = tm.narrow_pack(post, z, {0, 1, 2, 3})
    assert len(pack) == 8 and len(set(pack)) == 8 and pack[0] == 0
    assert not set(pack[2:]) & {0, 1, 2, 3}


def test_statements_need_weight_and_agreement_and_respect_no():
    post = tm.fit(np.eye(3, len(tm.MEASURED) + len(tm.TAGS)), [])
    post.w[0], post.w_sd[0] = 1.0, 0.3
    tend = [{"feature": "bpm", "word": "速め", "share": .8, "pairs": 5}]
    got = tm.statements(post, tend, None, _TODAY)
    assert [g["statement"] for g in got] == ["速め曲が好き"] and got[0]["status"] == "未確認"
    assert tm.statements(post, [], None, _TODAY) == []                # 組がそろっていない
    no = {"lines": [{"feature": "bpm", "direction": "+", "status": "違う", "date": "2026-10-01"}]}
    assert tm.statements(post, tend, no, _TODAY) == []                # 90日聞かない
    later = tm.statements(post, tend, no, _date(2027, 1, 15))
    assert len(later) == 1


def test_confirmed_preference_is_the_starting_point():
    k = {"lines": [{"feature": "bpm", "direction": "-", "status": "そう"}]}
    assert tm.confirmed_prior(k)[0] == -tm.CONFIRMED_START


def test_brief_gives_two_core_and_one_trial_prompt():
    post = tm.fit(np.eye(3, len(tm.MEASURED) + len(tm.TAGS)), [])
    post.w[0], post.w_sd[0] = 1.0, 0.3
    b = tm.brief(post, {"lines": [{"feature": "brightness", "direction": "-", "status": "そう"}]})
    assert [x["kind"] for x in b] == ["芯", "芯", "ためし"]
    assert all(x["prompt"].startswith(tm.BRIEF_HEAD) for x in b)
    assert "落ち着いた低めの音" in b[0]["prompt"] and "速め" in b[0]["prompt"]


def test_state_uses_topic_and_ignores_trial_answers():
    shelf = {"songs": [dict(s, roles=["op"]) for s in _shelf(4)] + [{"id": "ed1", "roles": ["ed"], "features": {}}]}
    ans = [{"a": "s0", "b": "s1", "pick": "a", "topic": "op"}, {"a": "s2", "b": "s3", "pick": "a", "who": "ためし"}]
    st = tm.state(shelf, ans, "op", today=_TODAY)
    assert {r["id"] for r in st["summary"]["ranking"]} == {"s0", "s1"}
    assert {u["id"] for u in st["unheard"]} == {"s2", "s3"}


def _sim_answer(rng, s, a, b, bar=0.3, beta=1.5):
    d = s[a] - s[b]
    if abs(d) < 0.3:
        if min(s[a], s[b]) > bar + 0.5 and rng.random() < 0.5:
            return "both"
        if max(s[a], s[b]) < bar - 0.5 and rng.random() < 0.5:
            return "neither"
    return "a" if rng.random() < 1 / (1 + np.exp(-beta * d)) else "b"


def _sim_once(rng, n=36, d=5):
    z = np.zeros((n, len(tm.MEASURED) + len(tm.TAGS)))
    z[:, :d] = rng.normal(size=(n, d))
    s = z[:, :d] @ rng.normal(0, 0.6, d) + rng.normal(0, 0.8, n)
    ids = [str(i) for i in range(n)]
    idx = {k: i for i, k in enumerate(ids)}
    answers, heard = [], set()
    pack = [int(i) for i in rng.choice(n, 12, replace=False)]
    for rounds in (10, 8, 8):
        met, session = set(), []
        for r in range(rounds):
            post = tm.fit(z, [o for x in answers for o in tm.to_obs(x, idx, _TODAY)], ids=ids)
            if tm.early_stop(post, pack, session, r):
                break
            a, b = tm.next_pair(post, pack, heard, met)
            p = _sim_answer(rng, s, a, b)
            answers.append({"a": ids[a], "b": ids[b], "pick": p})
            heard |= {a, b}
            met.add((min(a, b), max(a, b)))
            session.append((a, b, p))
        post = tm.fit(z, [o for x in answers for o in tm.to_obs(x, idx, _TODAY)], ids=ids)
        pack = tm.narrow_pack(post, z, heard)
    pick = max(heard, key=lambda i: post.mu[i])
    return int(np.argsort(np.argsort(-s))[pick]) < 3


def test_three_sessions_find_a_true_top3_song_seven_in_ten():
    """作り物の答え（式と同じ形の好み・36曲）で、3回答えたあとの1位が本当の上位3曲に入る割合。"""
    rng = np.random.default_rng(1)
    hits = [_sim_once(rng) for _ in range(60)]
    assert sum(hits) / len(hits) >= 0.7, sum(hits) / len(hits)
