"""B ロール（画像インサート）の案（backend/program_package/inserts.py）。

人物の写真も字幕の全文もリポジトリに置かないので、作った字幕・作った地図・作った絵で確かめる。
久木田回の実物での確かめは PR の本文と knowledge に残す。
"""
import json
import shutil
import subprocess

import pytest
from PIL import Image

from backend.program_package import inserts as ins

PEOPLE = ["北原"]


def caps(*rows):
    return [{"start": a, "end": b, "text": t} for a, b, t in rows]


def face(x, y):
    return {"box": [x, y, x + 120, y + 150], "score": 0.9}


def the_map(seconds=120, faces=((300, 200), (850, 200)), board=(60.0, 66.0), cut=None):
    frames = []
    for i in range(seconds * 2):
        t = i / 2
        r = {"t": t, "faces": [face(*f) for f in faces], "motion": 0.5 if cut == t else 0.01}
        if board[0] <= t <= board[1]:
            r["board"] = [200, 150, 520, 510]
        frames.append(r)
    return {"version": 1, "size": [1280, 720], "fps": 2.0, "duration": float(seconds), "frames": frames}


CAPS = caps((10, 12, "今日は縁の話を"), (13, 16, "聞いていきます"), (70, 72, "この「縁」の字ですが"),
            (72.2, 75, "とても素敵ですね"), (75.3, 78, "ありがとうございます"), (100, 103, "剣閃というフォントが"),
            (103.2, 106, "あるんですよね"))
SETUP = {"board_keywords": ["縁"]}


@pytest.fixture
def material(tmp_path):
    Image.new("RGB", (800, 600), (200, 30, 30)).save(tmp_path / "kensen.png")
    return {"id": "kensen", "file": "kensen.png", "keywords": ["剣閃"], "rights": "own", "people": "none", "ai_generated": False}


def test_収録の中の絵は映った後の話にだけ出す():
    plan = ins.propose({}, CAPS, the_map(), SETUP)
    assert [(it["at"], it["source"]["id"]) for it in plan["items"]] == [(70, "board")]
    assert plan["items"][0]["source"]["crop"] == [200, 150, 520, 510]
    assert any("先に見せない" in s["reason"] for s in plan["skipped"])


def test_始まりと終わりは字幕の切れ目で4から8秒():
    it = ins.propose({}, CAPS, the_map(), SETUP)["items"][0]
    assert (it["at"], it["seconds"]) == (70, 5.0)  # 70〜75（2枚目の字幕の終わり）


@pytest.mark.parametrize("rows,want", [
    (((70, 71.5, "縁"), (80, 82, "次")), (70, 74.0)),             # 短い字幕の後は間に残す。次の字幕には掛けない
    (((70, 71.5, "縁"), (72.5, 76, "次")), (70, 76)),             # 4 秒の中に出だしが来る字幕は終わりまで
    (((70, 90, "縁の長い話"),), (70, 78.0)),                       # 8 秒を超える 1 枚は 8 秒で切る
    (((70, 73, "縁"), (73.2, 79.5, "長め")), (70, 74.0)),         # 取り込むと 8 秒を超えるなら手前の切れ目（＋間）
])
def test_終わりの決まり(rows, want):
    c = caps(*rows)
    assert ins.slot(c, 0, []) == want


def test_地図が無ければ小窓にしない():
    it = ins.propose({}, CAPS, None, {"recording_sources": [{"id": "x", "at": 5, "keywords": ["縁"]}]})["items"][0]
    assert it["mode"] == "full"


def test_人が指した収録の絵を素材に見せかけることはできない():
    src = ins.extra_sources({"recording_sources": [{"id": "x", "at": 5, "keywords": ["縁"], "kind": "material"}]})
    assert src[0]["kind"] == "recording"


def test_承認の後に飾りが変わって重なったら止まる(tmp_path):
    pkg = tmp_path / "p.txt"
    pkg.write_text("▼チャプター\n0:00 はじめ\n0:30 つぎ\n", encoding="utf-8")
    spec = {"package": str(pkg), "chapters_skip": ["はじめ", "つぎ"]}
    plan = ins.propose(spec, CAPS, the_map(), SETUP)
    ins.decide(plan, [plan["items"][0]["id"]], ins.APPROVED, by="北原", evidence="チャット", people=PEOPLE)
    assert len(ins.ready(plan, spec, PEOPLE)) == 1
    with pytest.raises(ins.InsertError, match="重なっています"):
        ins.ready(plan, {**spec, "telops": [{"at": 71, "head": "後から足した", "body": "x"}]}, PEOPLE)


def test_字幕が変わったら承認した案は入れずに止まる(tmp_path):
    plan = ins.propose({}, CAPS, the_map(), SETUP)
    ins.decide(plan, [plan["items"][0]["id"]], ins.APPROVED, by="北原", evidence="チャット", people=PEOPLE)
    plan["base"] = {"captions": ins.captions_sha(CAPS)}
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"segments": CAPS}), encoding="utf-8")
    assert len(ins.ready(plan, {"lock": str(lock)}, PEOPLE)) == 1
    lock.write_text(json.dumps({"segments": CAPS[1:]}), encoding="utf-8")
    with pytest.raises(ins.InsertError, match="字幕"):
        ins.ready(plan, {"lock": str(lock)}, PEOPLE)


def test_頭に掛かる小窓は書き出す前に見つかる():
    m = the_map()
    it = ins.propose({}, CAPS, m, SETUP)["items"][0]
    assert ins.head_hits([it], m) == []
    assert ins.head_hits([{**it, "box": [280, 180, 600, 420]}], m) == [it["id"]]


def test_場面の切れ目はまたがない():
    it = ins.propose({}, CAPS, the_map(cut=73.5), SETUP)["items"][0]
    assert it["at"] + it["seconds"] < 73.5


def test_小窓は頭の来る所と字幕の帯に掛からない():
    m = the_map()
    it = ins.propose({}, CAPS, m, SETUP)["items"][0]
    assert it["mode"] == "pip"
    x0, y0, x1, y1 = it["box"]
    assert y1 <= ins.FLOOR and x0 >= ins.FRAME[0] and x1 <= ins.FRAME[2]
    for z in ins.vision.head_zones(m, it["at"], it["seconds"]):
        assert x1 <= z[0] or z[2] <= x0 or y1 <= z[1] or z[3] <= y0


def test_壁が無ければ全画面で字幕の帯は残す():
    m = the_map(faces=((60, 60), (330, 60), (600, 60), (870, 60)))
    it = ins.propose({}, CAPS, m, SETUP)["items"][0]
    assert it["mode"] == "full" and it["box"][3] <= ins.FLOOR
    assert ins.card(it, Image.new("RGB", (320, 360))).getpixel((640, ins.FLOOR + 40))[3] == 0


@pytest.mark.parametrize("change,word", [({"rights": "third_party"}, "権利"), ({"rights": None}, "権利"),
                                         ({"people": "unknown"}, "写り込み"), ({"ai_generated": True}, "AI"), ({"ai_generated": None}, "未記入"),
                                         ({"kind": "video"}, "動画")])
def test_使えない素材は案に出さず理由を出す(material, tmp_path, change, word):
    plan = ins.propose({}, CAPS, the_map(), {}, [{**material, **change}], root=tmp_path)
    assert plan["items"] == [] and word in plan["excluded"][0]["reason"]


def test_素材は話に合わせて出し絵が無い言葉は素材待ちに出す(material, tmp_path):
    spec = {"telops": [{"at": 300, "head": "『墨』", "body": "x"}], "title": {"guest": "山田太郎"}}
    c = CAPS + caps((110, 113, "墨という雑誌に"), (114, 116, "山田太郎さんが"))
    plan = ins.propose(spec, c, the_map(), {}, [material], "■ タグ\n剣閃, 山田太郎, 無い言葉\n", tmp_path)
    assert [(it["keyword"], it["at"]) for it in plan["items"]] == [("剣閃", 100)]
    assert [w["keyword"] for w in plan["wanted"]] == ["墨"]  # 絵のある言葉・人の名前・話に出ない言葉は出さない


def test_絵はあるが使えない言葉は何が足りないかを素材待ちに書く(material, tmp_path):
    spec = {"telops": [{"at": 300, "head": "剣閃", "body": "x"}]}
    plan = ins.propose(spec, CAPS, the_map(), {}, [{**material, "rights": "third_party"}], root=tmp_path)
    assert plan["items"] == [] and "権利" in plan["wanted"][0]["note"]


def test_素材が増えても承認した案の名前は変わらない(material, tmp_path):
    one = ins.propose({}, CAPS, the_map(), SETUP)
    early = {**material, "keywords": ["聞いて"]}  # 色紙より前の時刻に入る素材
    two = ins.propose({}, CAPS, the_map(), SETUP, [early], root=tmp_path)
    assert len(two["items"]) == 2 and one["items"][0]["id"] in [it["id"] for it in two["items"]]


def test_承認は人だけで証拠が要る():
    plan = ins.propose({}, CAPS, the_map(), SETUP)
    with pytest.raises(ins.InsertError, match="AI は承認しない"):
        ins.decide(plan, ["board-0110"], ins.APPROVED, by="claude-code", evidence="x", people=PEOPLE)
    with pytest.raises(ins.InsertError, match="evidence"):
        ins.decide(plan, ["board-0110"], ins.APPROVED, by="北原", evidence=" ", people=PEOPLE)
    assert ins.approved(plan) == []
    ins.decide(plan, ["board-0110"], ins.APPROVED, by="北原", evidence="11/12 チャット「入れて」", people=PEOPLE)
    assert [it["id"] for it in ins.approved(plan)] == ["board-0110"]


def test_承認できない人の名前が書かれた案は入らない():
    plan = ins.propose({}, CAPS, the_map(), SETUP)
    ins.decide(plan, ["board-0110"], ins.APPROVED, by="北原", evidence="チャット", people=PEOPLE)
    plan["items"][0]["decision"]["by"] = "claude-code"  # 置き場を手で書き換えた場合
    assert ins.approved(plan) == []


def test_台帳の承認できる人にAIの名前は無い():
    assert ins.approvers() and not any("claude" in a.lower() or "ai" == a.lower() for a in ins.approvers())


def test_承認の後に中身が変わった案は入らない():
    plan = ins.propose({}, CAPS, the_map(), SETUP)
    ins.decide(plan, ["board-0110"], ins.APPROVED, by="北原", evidence="チャット", people=PEOPLE)
    plan["items"][0]["at"] += 3
    assert ins.approved(plan) == []


def test_出し直しても同じ案の承認は残り変わった案は提案に戻る():
    old = ins.propose({}, CAPS, the_map(), SETUP)
    ins.decide(old, ["board-0110"], ins.APPROVED, by="北原", evidence="チャット", people=PEOPLE)
    old["setup"] = SETUP
    same = ins.merge(old, ins.propose({}, CAPS, the_map(), SETUP))
    assert same["items"][0]["state"] == ins.APPROVED and same["setup"] == SETUP and ins.approved(same)
    moved = ins.merge(old, ins.propose({}, caps((71, 76, "縁の字")), the_map(), SETUP))
    assert moved["items"][0]["state"] == ins.PROPOSED


def test_素材の中身が変わったら止まる(material, tmp_path):
    plan = ins.propose({}, CAPS, the_map(), {}, [material], root=tmp_path)
    Image.new("RGB", (800, 600), (0, 0, 255)).save(tmp_path / "kensen.png")
    with pytest.raises(ins.InsertError, match="中身"):
        ins.picture(plan["items"][0], None, root=tmp_path)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg が無い")
def test_承認した分だけ入った版を書き出す(material, tmp_path):
    video = tmp_path / "base.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=10:d=110",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", str(video)], check=True)
    plan = ins.propose({}, CAPS, the_map(), SETUP, [material], root=tmp_path)
    assert [it["id"] for it in plan["items"]] == ["board-0110", "kensen-0140"]
    with pytest.raises(ins.InsertError, match="承認済みの案がありません"):
        ins.render(plan, video, tmp_path / "x.mp4", root=tmp_path)
    ins.decide(plan, ["kensen-0140"], ins.APPROVED, by="北原", evidence="チャット", people=PEOPLE)
    out = ins.render(plan, video, tmp_path / "out.mp4", root=tmp_path, preset="ultrafast")

    def pixel(t, box):
        x, y = (box[0] + box[2]) // 4, (box[1] + box[3]) // 4  # 640x360 での真ん中
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        return tuple(raw[(y * 640 + x) * 3:(y * 640 + x) * 3 + 3])

    r, g, b = pixel(102, plan["items"][1]["box"])
    assert r > 150 and g < 80  # 承認した素材（赤）が入っている
    r, g, b = pixel(72, plan["items"][0]["box"])
    assert abs(r - g) < 20  # 承認していない案は入っていない（灰色のまま）
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(out)], capture_output=True, text=True).stdout)
    assert abs(dur - 110) < 0.5


def test_久木田回の案の置き場は読めて未承認の物は入らない():
    path = ins.STORE / "20250922_久木田ヒロノブ.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert plan["setup"]["board_keywords"] == ["縁"]
    for it in plan["items"]:
        assert it["fingerprint"] == ins.fingerprint(it)
        assert it["state"] != ins.APPROVED or it["decision"]["by"] in ins.approvers()


def test_決まりが変わって秒だけ違う案は人が見て決めた方を残す():
    old = ins.propose({}, CAPS, the_map(), SETUP)
    ins.decide(old, ["board-0110"], ins.APPROVED, by="北原", evidence="チャット", people=PEOPLE)
    new = ins.propose({}, CAPS, the_map(), SETUP)
    new["items"][0]["seconds"] -= 1
    new["items"][0]["fingerprint"] = ins.fingerprint(new["items"][0])
    plan = ins.merge(old, new)
    assert plan["items"][0]["seconds"] == old["items"][0]["seconds"] and ins.approved(plan, PEOPLE)
