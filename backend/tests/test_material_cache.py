"""素材の隣に置く AI の控え（校閲・音声認識・映像の切り替わり）の名前（2026-10-18）。

それまで鍵は素材の場所・大きさ・更新時刻だった。素材を別の場所（クラウドの新しいコンテナ・
Drive から取り直した素材）に置くと控えが見つからず、保存した控えを戻しても AI を呼び直していた。

守りたい性質:

1. 中身が同じ素材なら、置き場所・ファイル名・更新時刻が違っても同じ名前の控えを指す
2. 中身が違えば別の控え
3. 同じ素材の控えはどれも、文字起こしの控え（`_gemini_*`）と同じ8文字を名前に持つ
4. 前の鍵で作った控えしか無ければ、新しい名前に写して使う（前の控えは消さない）
5. 同じ process で、変わっていない素材を読み直さない（raw4 の結合は 827MB、撮影生データは数GB）
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

import cut_plan
from subtitle_engine import aligner
from subtitle_engine.video_hash import compute_video_hash


def _proofread(media):
    from agents.workers.proofread_worker import _memo_for
    return _memo_for(media).path


CACHES = [
    pytest.param(_proofread, "_proofread_", "", id="校閲"),
    pytest.param(lambda m: aligner._cache_path(str(m)), "_align_rz_", aligner.MODEL_NAME, id="音声認識"),
    pytest.param(cut_plan._shots_cache_path, "_shots_", "scdet", id="映像の切り替わり"),
]

LATER = 1_700_000_000 * 10 ** 9  # 更新時刻（ナノ秒）


@pytest.mark.parametrize("name_of, prefix, salt", CACHES)
def test_the_same_material_points_to_the_same_cache_wherever_it_is(tmp_path, name_of, prefix, salt):
    a = tmp_path / "a" / "raw4_concat.mp4"
    b = tmp_path / "b" / "joined.mp4"
    for p in (a, b):
        p.parent.mkdir()
        p.write_bytes(b"material" * 100)
    os.utime(b, ns=(LATER, LATER))

    assert name_of(a).name == name_of(b).name
    assert name_of(a).parent == a.parent and name_of(b).parent == b.parent


@pytest.mark.parametrize("name_of, prefix, salt", CACHES)
def test_a_different_material_points_to_a_different_cache(tmp_path, name_of, prefix, salt):
    media = tmp_path / "raw.mp4"
    media.write_bytes(b"x" * 100)
    first = name_of(media)

    media.write_bytes(b"y" * 100)  # 大きさは同じ
    os.utime(media, ns=(LATER, LATER))  # 書き直せば更新時刻は進む

    assert name_of(media) != first


@pytest.mark.parametrize("name_of, prefix, salt", CACHES)
def test_every_cache_of_a_material_carries_the_eight_letters_of_its_transcription(tmp_path, name_of, prefix,
                                                                                  salt):
    media = tmp_path / "raw.mp4"
    media.write_bytes(b"material")

    assert name_of(media).name == f"{prefix}{compute_video_hash(media)}.json"


@pytest.mark.parametrize("name_of, prefix, salt", CACHES)
def test_a_cache_made_under_the_old_name_is_taken_over(tmp_path, name_of, prefix, salt):
    media = tmp_path / "raw.mp4"
    media.write_bytes(b"material")
    st = media.stat()
    old_key = f"{media.resolve()}|{st.st_size}|{int(st.st_mtime)}" + (f"|{salt}" if salt else "")
    old = tmp_path / f"{prefix}{hashlib.sha1(old_key.encode()).hexdigest()[:8]}.json"
    old.write_text('{"made": "before"}', encoding="utf-8")

    new = name_of(media)

    assert new != old and new.read_text(encoding="utf-8") == '{"made": "before"}'
    assert old.read_text(encoding="utf-8") == '{"made": "before"}'


@pytest.mark.parametrize("name_of, prefix, salt", CACHES)
def test_a_material_that_has_not_changed_is_not_read_again(tmp_path, name_of, prefix, salt):
    media = tmp_path / "raw.mp4"
    media.write_bytes(b"x" * 100)
    first = name_of(media)

    # 大きさ・更新時刻・inode を変えずに中身だけ変える（読み直せば名前が変わる）
    st = media.stat()
    with open(media, "r+b") as f:
        f.write(b"y")
    os.utime(media, ns=(st.st_atime_ns, st.st_mtime_ns))

    assert name_of(media) == first


def test_a_recognition_made_by_another_model_is_made_again(tmp_path, monkeypatch):
    # 鍵にモデルの名前が入っていたので、モデルを替えれば別の控えになっていた。控えの中の名前で見る
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    aligner._cache_path(str(media)).write_text(
        json.dumps({"version": aligner.CACHE_VERSION, "model": "another-model", "timeline": aligner.TIMELINE,
                    "tokens": [["あ", 1.0]]}), encoding="utf-8")
    monkeypatch.setattr(aligner, "available", lambda: True)
    monkeypatch.setattr(aligner, "recognize", lambda m: [("い", 2.0)])

    assert aligner.tokens_for(str(media)) == [("い", pytest.approx(2.0 + aligner.LAG_SEC))]
    cached = json.loads(aligner._cache_path(str(media)).read_text(encoding="utf-8"))
    assert cached["model"] == aligner.MODEL_NAME
