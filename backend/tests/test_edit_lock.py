"""承認した編集の固定（2026-10-19）。

台帳だけでは、人が見ていない所の字が AI の揺れで変わる（raw4 のキャッシュ無しの作り直しで 13%）。
承認した書き出しの区間と字幕を素材に結び付けて残し、AI を呼ばずにそのまま作り直す。
"""
import json
import subprocess

import pytest

from subtitle_engine import edit_lock, review_sheet

APPROVED = {"segments": [{"start": 0.2, "end": 1.6, "text": "こんにちは\n書家の北原美麗です"},
                         {"start": 2.0, "end": 3.4, "text": "よろしくお願いします"}],
            "ranges": [[0.5, 2.5], [3.5, 5.5]], "cut_points": [2.0]}


@pytest.fixture
def material(tmp_path):
    path = tmp_path / "raw.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "6", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True, timeout=120)
    return path


def test_a_rebuild_from_the_lock_has_the_approved_captions_and_cut(tmp_path, material):
    lock = edit_lock.make(APPROVED, material, run="r61", label="61回目")
    out = tmp_path / "again.mp4"
    side = edit_lock.render(lock, material, out)
    assert review_sheet.compare(APPROVED, json.loads(side.read_text(encoding="utf-8"))) == []
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True, check=True).stdout)
    assert abs(dur - 4.0) < 0.15


def test_another_material_is_refused(tmp_path, material):
    lock = edit_lock.make(APPROVED, material, run="r61", label="61回目")
    other = tmp_path / "other.mp4"
    other.write_bytes(material.read_bytes()[:-100] + b"\x00" * 100)
    with pytest.raises(edit_lock.LockError, match="素材が違います"):
        edit_lock.render(lock, other, tmp_path / "x.mp4")


def test_a_lock_whose_captions_were_changed_after_approval_is_refused(material):
    lock = edit_lock.make(APPROVED, material, run="r61", label="61回目")
    lock["segments"][0]["text"] = "こんにちは"
    with pytest.raises(edit_lock.LockError, match="変わっています"):
        edit_lock.check(lock, material)


def _lock_without_material():
    approved = {"segments": [{"start": 0.2, "end": 1.6, "text": "こんにちは\n書家の北原美麗です"},
                             {"start": 2.0, "end": 3.4, "text": "よろしくお願いします"}],
                "ranges": [[0.5, 2.5], [3.5, 5.5]]}
    return {"version": 1, "material": {"name": "raw.mp4", "key": "k"},
            "approved": {"run": "r61", "label": "61回目", "sha256": edit_lock._sidecar_sha(approved)}, **approved}


def test_amend_fixes_only_the_wrong_letters_and_keeps_the_record():
    lock = _lock_without_material()
    new = edit_lock.amend(lock, [{"at": 1.0, "from": "北原美麗", "to": "北原美麗（書家）"}],
                          by="北原", evidence="2026-11-12 チャット")
    assert new["segments"][0]["text"] == "こんにちは\n書家の北原美麗（書家）です"
    assert new["segments"][1] == lock["segments"][1]
    assert new["ranges"] == lock["ranges"]
    rec = new["amendments"][-1]
    assert rec["by"] == "北原" and rec["based_on"] == lock["approved"]["sha256"]
    # 直した固定は、それ自体として形が通る（render の check の最初の 2 段）
    assert edit_lock._sidecar_sha(edit_lock.sidecar_of(new)) == new["approved"]["sha256"]
    assert lock["segments"][0]["text"] == "こんにちは\n書家の北原美麗です"  # 元は変えない


def test_amend_across_a_line_break():
    new = edit_lock.amend(_lock_without_material(), [{"at": 0.5, "from": "は書家", "to": "は 書家"}],
                          by="北原", evidence="x")
    assert new["segments"][0]["text"].replace("\n", "") == "こんにちは 書家の北原美麗です"
    assert "\n" in new["segments"][0]["text"]


def test_amend_refuses_a_fix_that_does_not_hit():
    with pytest.raises(edit_lock.LockError):
        edit_lock.amend(_lock_without_material(), [{"at": 30.0, "from": "北原", "to": "x"}], by="北原", evidence="x")
    with pytest.raises(edit_lock.LockError):
        edit_lock.amend(_lock_without_material(), [{"at": 1.0, "from": "北原", "to": "x"}], by="", evidence="x")


def test_an_amended_lock_renders_the_fixed_caption(tmp_path, material):
    lock = edit_lock.make({k: v for k, v in _lock_without_material().items() if k in ("segments", "ranges")}, material, run="r61", label="61回目")
    new = edit_lock.amend(lock, [{"at": 2.5, "from": "よろしく", "to": "どうぞよろしく"}], by="北原", evidence="x")
    side = edit_lock.render(new, material, tmp_path / "fixed.mp4")
    assert json.loads(side.read_text(encoding="utf-8"))["segments"][1]["text"] == "どうぞよろしくお願いします"
