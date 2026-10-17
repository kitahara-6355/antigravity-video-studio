"""校正台帳（人が通しで見て直した字幕）を書き出しのたびに当てる。

北原さんが 52回目の 18分までを見て 14か所を直した（2026-10-17）。文字起こしと校閲（AI）は呼ぶたびに
揺れるので、人の直しは素材ごとの台帳に残し、AI の後に機械的に当てる。
"""
import json
from pathlib import Path

import pytest

from subtitle_engine import review_ledger

REPO = Path(__file__).resolve().parents[2]
RAW4 = REPO / "backend" / "config" / "reviews" / "raw4_20250922.json"
# 52回目の校閲の後・整形の前の行（素材の秒）のうち、台帳が直す行だけを写したもの
RAW4_LINES = Path(__file__).with_name("fixtures") / "review_raw4_lines52.json"


def _seg(a, b, text):
    return {"start": a, "end": b, "sourceStart": a, "sourceEnd": b, "text": text}


def _ledger(corrections=(), glossary=()):
    return {"version": 1, "corrections": list(corrections), "glossary": list(glossary)}


def test_a_correction_replaces_the_words_in_the_line_spoken_at_that_time():
    segs = [_seg(560.0, 562.0, "だから僕は印象的な仕事がそれなの。"), _seg(561.5, 563.8, "で、焦るわけ。")]
    report = review_ledger.apply(segs, _ledger([{"id": "c1", "at": 561.7, "from": "焦るわけ", "to": "折れるわけ"}]))
    assert segs[1]["text"] == "で、折れるわけ。"
    assert segs[0]["text"] == "だから僕は印象的な仕事がそれなの。"
    assert [r["id"] for r in report["applied"]] == ["c1"]
    assert report["missing"] == [] and report["already"] == []


def test_punctuation_and_spaces_do_not_stop_a_correction_from_matching():
    # 字幕で見えるのは句読点を外した形（「ホウライ　精密工業」）。行には「、」が残っている
    segs = [_seg(426.3, 430.4, "その、ホウライ、精密工業っていう会社が、一時的に買収したじゃないですか。")]
    review_ledger.apply(segs, _ledger([{"id": "c3", "at": 427.4, "from": "ホウライ　精密工業", "to": "ホンハイ精密工業"}]))
    assert segs[0]["text"] == "その、ホンハイ精密工業っていう会社が、一時的に買収したじゃないですか。"


def test_the_line_nearest_to_the_time_wins_when_the_words_occur_twice():
    segs = [_seg(551.0, 553.0, "で、焦るわけ。"), _seg(561.5, 563.8, "で、焦るわけ。")]
    review_ledger.apply(segs, _ledger([{"id": "c1", "at": 562.0, "from": "焦るわけ", "to": "折れるわけ"}]))
    assert [s["text"] for s in segs] == ["で、焦るわけ。", "で、折れるわけ。"]


def test_a_correction_far_from_its_time_is_not_applied():
    segs = [_seg(100.0, 102.0, "で、焦るわけ。")]
    report = review_ledger.apply(segs, _ledger([{"id": "c1", "at": 561.7, "from": "焦るわけ", "to": "折れるわけ"}]))
    assert segs[0]["text"] == "で、焦るわけ。"
    assert [r["id"] for r in report["missing"]] == ["c1"]


def test_a_correction_already_right_in_the_transcript_is_reported_and_left_alone():
    # キャッシュ無しで起こし直すと、聞き違いが消えていることがある
    segs = [_seg(561.5, 563.8, "で、折れるわけ。")]
    report = review_ledger.apply(segs, _ledger([{"id": "c1", "at": 561.7, "from": "焦るわけ", "to": "折れるわけ"}]))
    assert segs[0]["text"] == "で、折れるわけ。"
    assert [r["id"] for r in report["already"]] == ["c1"]


def test_a_correction_that_matches_nowhere_is_reported_as_missing():
    segs = [_seg(561.5, 563.8, "で、怒れるわけ。")]
    report = review_ledger.apply(segs, _ledger([{"id": "c1", "at": 561.7, "from": "焦るわけ", "to": "折れるわけ"}]))
    assert segs[0]["text"] == "で、怒れるわけ。"
    assert [r["id"] for r in report["missing"]] == ["c1"]


def test_a_glossary_entry_replaces_its_wrong_forms_throughout_the_material():
    segs = [_seg(911.1, 920.9, "その前の剣先っていうフォントがあるですよね。剣先っていうね先生の作ったフォントが有名ですよね。"),
            _seg(958.0, 961.0, "あの、そこで僕のその剣先が使われてるんですよね。")]
    report = review_ledger.apply(segs, _ledger(glossary=[{"term": "剣閃", "wrong": ["剣先"]}]))
    assert "剣先" not in "".join(s["text"] for s in segs)
    assert segs[1]["text"] == "あの、そこで僕のその剣閃が使われてるんですよね。"
    assert report["glossary"] == {"剣閃": 3}


def test_corrections_are_applied_before_the_glossary():
    # 場所を決めた直しは用語の置き換えより先に当てる（直しの from が用語の誤りを含んでいても当たる）
    segs = [_seg(10.0, 12.0, "ここ剣先書いとくわけ。")]
    review_ledger.apply(segs, _ledger([{"id": "c", "at": 11.0, "from": "ここ剣先書いとくわけ", "to": "ここ剣閃を書いてください"}],
                                      [{"term": "剣閃", "wrong": ["剣先"]}]))
    assert segs[0]["text"] == "ここ剣閃を書いてください。"


def test_a_ledger_is_read_from_a_file_and_an_absent_path_means_no_ledger(tmp_path):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(_ledger([{"id": "c1", "at": 1.0, "from": "a", "to": "b"}]), ensure_ascii=False),
                 encoding="utf-8")
    assert review_ledger.load(p)["corrections"][0]["id"] == "c1"
    assert review_ledger.load("") is None
    with pytest.raises(FileNotFoundError):
        review_ledger.load(tmp_path / "missing.json")


def test_a_ledger_with_a_broken_entry_is_refused(tmp_path):
    for bad in ({"id": "c1", "at": "x", "from": "a", "to": "b"},
                {"id": "c1", "at": 1.0, "from": "", "to": "b"},
                {"id": "c1", "at": 1.0, "from": "a"}):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(_ledger([bad]), ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError):
            review_ledger.load(p)


def test_the_raw4_ledger_is_well_formed():
    ledger = review_ledger.load(RAW4)
    ids = [c["id"] for c in ledger["corrections"]]
    assert len(ids) == len(set(ids))
    for g in ledger["glossary"]:
        assert all(g["term"] not in w for w in g.get("wrong", []))


def test_the_raw4_ledger_applies_to_every_line_it_was_written_for():
    """52回目の行に当てると、北原さんの14か所を含む直しが全部当たり、誤りの字が残らない。"""
    lines = json.loads(RAW4_LINES.read_text(encoding="utf-8"))
    report = review_ledger.apply(lines, review_ledger.load(RAW4))
    assert report["missing"] == [] and report["already"] == []
    text = "".join(s["text"] for s in lines)
    for wrong in ("ところにご", "ホテイフーズ", "ホウライ", "レスキュー", "早川式繰出鉛筆書", "焦る", "藤田さん",
                  "安心そう", "新・日本", "一日一書", "おそらって", "和歌山", "北原美麗の生徒", "10月にはね",
                  "剣先", "Bオリジナル", "伝えたい言葉大賞"):
        assert wrong not in text, wrong
    for right in ("ところに移行", "はごろもフーズ", "ホンハイ精密工業", "レール引いて", "ここ Be Original 書いてください",
                  "こうやって Be Original 書くのよ", "折れるわけ", "久木田さん", "泣きそうになった", "暑いわ、折れるわ",
                  "「森羅万象」と、あと「日々是好日」", "おそらく", "私のこの美麗書院の", "11月にはね"):
        assert right in text, right
    # Sharp の歴史を語る所（6分53秒）の「早川式繰出鉛筆」は正しいので残る
    assert "早川式繰出鉛筆っていう名前で" in text


def _proofread(monkeypatch, ctx, rewrite=lambda t: t):
    """校閲（AI）を ``rewrite`` に差し替えて ProofreadWorker を1回走らせる（API は呼ばない）。"""
    import asyncio
    import sys
    sys.path.insert(0, str(REPO / "backend"))
    from agents.workers import proofread_worker
    from subtitle_engine import ai_proofreader

    def fake(segs, return_stats=True, **kw):
        return [{**s, "text": rewrite(s["text"])} for s in segs], {"total_batches": 1}

    monkeypatch.setattr(proofread_worker, "_referee_for", lambda video_path: None)
    monkeypatch.setattr(proofread_worker, "_memo_for", lambda video_path: None)
    monkeypatch.setattr(ai_proofreader, "proofread_segments", fake)
    return asyncio.run(proofread_worker.ProofreadWorker().execute(ctx))


def _ctx(ledger_path, *segs):
    from tests.fixtures.mock_pipeline import create_mock_ctx
    ctx = create_mock_ctx(segments=0)
    ctx.segments = [dict(s) for s in segs]
    ctx.review_ledger = str(ledger_path)
    return ctx


def test_the_proofread_step_applies_the_ledger_after_the_ai_and_before_formatting(monkeypatch, tmp_path):
    # 校閲（AI）が「折れる」を「焦る」に書き換えても、人の直しが後から当たる。整形は直しの後に走る
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(_ledger([{"id": "c7", "at": 561.7, "from": "焦るわけ", "to": "折れるわけ"}]),
                            ensure_ascii=False), encoding="utf-8")
    ctx = _ctx(p, _seg(561.5, 563.8, "で、折れるわけ。"))
    result = _proofread(monkeypatch, ctx, rewrite=lambda t: t.replace("折れる", "焦る"))
    text = "".join(s["text"] for s in ctx.segments)
    assert "折れるわけ" in text and "焦る" not in text
    assert "、" not in text and "。" not in text
    assert [r["id"] for r in result.data["review"]["applied"]] == ["c7"]
    assert result.data["review"]["ledger"] == str(p)
    assert "人の直し1件" in result.detail


def test_a_correction_the_run_cannot_place_is_raised_as_a_warning(monkeypatch, tmp_path):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(_ledger([{"id": "c7", "at": 561.7, "from": "焦るわけ", "to": "折れるわけ"}]),
                            ensure_ascii=False), encoding="utf-8")
    ctx = _ctx(p, _seg(561.5, 563.8, "で、怒れるわけ。"))
    result = _proofread(monkeypatch, ctx)
    assert "当たらない1件" in result.detail
    assert any("1件の直しが当たりませんでした（素材の 9分21秒）" in w for w in ctx.warnings)


def test_no_ledger_leaves_the_proofread_step_as_it_was(monkeypatch):
    ctx = _ctx("", _seg(561.5, 563.8, "で、焦るわけ。"))
    result = _proofread(monkeypatch, ctx)
    assert result.data["review"] == {}
    assert "人の直し" not in result.detail


def test_the_command_refuses_a_ledger_it_cannot_read_before_calling_any_api(tmp_path, capsys):
    from agents import pipeline_coordinator
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    assert pipeline_coordinator.main([str(video), "--review", str(tmp_path / "missing.json")]) == 1
    assert "校正台帳を読めません" in capsys.readouterr().out
