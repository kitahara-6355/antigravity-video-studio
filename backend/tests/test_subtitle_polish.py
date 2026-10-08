"""字幕の仕上げ（2026-10-06 ユーザー指摘・恒久対策）。

- 句読点を出さない
- 「では」など話題に掛からない文頭語は「、」が無くても外す
- 字幕の切れ目は行の折り目より優先（「この対談では、/各界で」＋「ご活躍…」を作らない）
- 校閲（AI）が落ちたバッチは分けて再実行し、残れば品質ゲートが合格させない
- 辞書の hint は機械的に置き換えず、校閲に文脈で判断させる
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from subtitle_engine import text_formatter as tf  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("はい、いえいえ。", "はい　いえいえ"),
    ("こんにちは、\n書家の北原美麗です。", "こんにちは\n書家の北原美麗です"),
    ("本当ですか？", "本当ですか？"),
    ("。", ""),
    # 数字の桁区切り・小数点は句読点ではない（27分03秒の「1,000、1,500人」が「1　000　1　500人」になった）
    ("1,000、1,500人教えた", "1,000　1,500人教えた"),
    ("２，０００円です。", "２，０００円です"),
    ("1．5倍", "1．5倍"),
])
def test_strip_punctuation(text, expected):
    assert tf.strip_punctuation(text) == expected


def test_captions_remember_where_punctuation_was_taken_out():
    # 句読点を外すと、改行や字幕の終わりが句読点の跡だったかが分からなくなる。後で字幕を組み直すとき
    # （短すぎる字幕をまとめる・移す）に語が詰まらないよう、外す前に覚えておく（15分59秒・28回目）
    assert tf._strip_punctuation_enabled()
    [comma] = tf.format_segments([{"text": "そうなんですよ、すごく人気だと思いますよ。", "start": 0.0, "end": 3.0}], 18)
    assert comma["text"] == "そうなんですよ\nすごく人気だと思いますよ"
    assert comma["_break_punct"] is True and comma["_ends_punct"] is True
    [plain] = tf.format_segments([{"text": "筆文字がいいところに出てくる機会が多いですよね", "start": 0.0, "end": 3.0}], 18)
    assert "\n" in plain["text"]
    assert not plain.get("_break_punct") and not plain.get("_ends_punct")


def test_a_sentence_head_ne_is_not_shown():
    # 実例（17分58秒・33分48秒）: 「ね、あわよくば…」「ね、いくらおいしいものを…」の文頭の「ね」が
    # 字幕の頭に残った。話題に触れない言葉なので外す（2026-10-06 ユーザー方針）
    text = "ね、あわよくば、その98%の人口の中から改めて古典書道学ぼうっていう人も出てくるかもしれない。"
    out = tf.format_segments([{"text": text, "start": 0.0, "end": 6.0}], 18)
    assert out and not out[0]["text"].startswith("ね")
    # 「、」が続かない「ね」（語の頭・文末）は残す
    assert tf.strip_lead_words("ねじを回すんですね。") == "ねじを回すんですね。"


def test_bare_lead_word_is_removed_without_comma():
    assert tf.strip_lead_words("では記念すべき第1回目", [], ["では"]) == "記念すべき第1回目"
    assert tf.strip_lead_words("では\n記念すべき", [], ["では"]) == "記念すべき"
    # 後ろにひらがなが続くのは別の語（「ではありません」）
    assert tf.strip_lead_words("ではありません", [], ["では"]) == "ではありません"
    # 文の途中の「では」は残す
    assert tf.strip_lead_words("この対談では各界の", [], ["では"]) == "この対談では各界の"


def test_default_rules_drop_dewa_and_punctuation():
    from template_constants import _DEFAULT_SUBTITLE_RULES as rules
    assert "では" in rules["omit_lead_words_bare"]
    assert rules["strip_punctuation"] is True


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_caption_break_beats_line_break():
    caps = tf.split_into_captions(
        "今回から始まるこの対談では、各界でご活躍されている方をお招きし、"
        "大切にされている言葉を書いていただきます。", 15, 2)
    assert caps[0].replace("\n", "").endswith("対談では、")
    assert not any(c.replace("\n", "").endswith("各界で") for c in caps)


def test_hint_entries_are_not_replaced_mechanically(tmp_path):
    import json
    from proper_noun_dict import ProperNounDictionary
    path = tmp_path / "pn.json"
    path.write_text(json.dumps({"version": 1, "entries": [
        {"id": "a", "incorrect": "読んでいただいて", "correct": "呼んでいただいて", "type": "hint"},
        {"id": "b", "incorrect": "初会", "correct": "初回", "type": "word"},
    ]}, ensure_ascii=False), encoding="utf-8")
    d = ProperNounDictionary(path)
    text, fixes = d.apply_corrections("本を読んでいただいて初会の")
    assert text == "本を読んでいただいて初回の"
    assert [f["corrected"] for f in fixes] == ["初回"]


def test_failed_batches_are_split_and_retried():
    from agents.workers.proofread_worker import _repair_failed_batches
    segs = [{"text": f"t{i}"} for i in range(8)]
    calls = []

    def fake(sub, return_stats=True):
        calls.append(len(sub))
        # 4行のまとまりは落ちる。2行なら通る
        if len(sub) > 2:
            return sub, {"failed_batches": 1, "accepted_items": 0}
        for s in sub:
            s["text"] += "!"
        return sub, {"failed_batches": 0, "accepted_items": len(sub)}

    stats = _repair_failed_batches(segs, {"failed_ranges": [[0, 8]], "failed_batches": 1}, fake)
    assert stats["failed_batches"] == 0 and stats["failed_ranges"] == []
    assert all(s["text"].endswith("!") for s in segs)
    assert calls[:2] == [4, 4]


def test_unrepaired_batches_stay_failed():
    from agents.workers.proofread_worker import _repair_failed_batches
    segs = [{"text": "x"} for _ in range(4)]
    stats = _repair_failed_batches(segs, {"failed_ranges": [[0, 4]], "failed_batches": 1},
                                   lambda sub, return_stats=True: (sub, {"failed_batches": 1}))
    assert stats["failed_batches"] > 0


def test_the_proofreading_memo_lives_next_to_the_source_and_follows_it(tmp_path):
    # 一度採った校閲の直しは素材ごとに控えて、次の書き出しでも使う（29回目で冒頭の直しが揺れた）
    from agents.workers.proofread_worker import _memo_for
    media = tmp_path / "raw.mp4"
    media.write_bytes(b"x")
    memo = _memo_for(media)
    assert memo is not None and memo.path.parent == tmp_path and memo.path.name.startswith("_proofread_")
    assert _memo_for(media).path == memo.path
    media.write_bytes(b"xy")  # 素材が変われば別の控え
    assert _memo_for(media).path != memo.path
    assert _memo_for(tmp_path / "missing.mp4") is None


def test_the_stage_says_which_model_made_the_corrections_taken_from_the_memo(monkeypatch):
    # 控えから使った直しは、この回にはどのモデルも呼んでいない。工程の結果に、控えから何行・
    # どのモデルの直しを使ったかを出す（モデルの見える化）
    import asyncio
    from agents.workers import proofread_worker
    from subtitle_engine import ai_proofreader
    from tests.fixtures.mock_pipeline import create_mock_ctx

    def fake(segs, return_stats=True, **kwargs):
        return segs, {"total_batches": 1, "failed_batches": 0, "total_retries": 0,
                      "accepted_items": len(segs), "failed_ranges": [],
                      "memo_hits": len(segs), "memo_models": ["gemini-3.5-flash-lite"]}

    monkeypatch.setattr(ai_proofreader, "proofread_segments", fake)
    monkeypatch.setattr(proofread_worker, "_referee_for", lambda path: None)
    monkeypatch.setattr(proofread_worker, "_memo_for", lambda path: None)
    res = asyncio.run(proofread_worker.ProofreadWorker().execute(create_mock_ctx(segments=3)))
    assert "校閲の控え3行（gemini-3.5-flash-lite）" in res.detail
    assert res.data["memo_hits"] == 3 and res.data["memo_models"] == ["gemini-3.5-flash-lite"]


def test_quality_gate_blocks_unproofread_subtitles(tmp_path, monkeypatch):
    from quality_gate_plugins import SubtitleCoverageCheck
    from subtitle_engine import coverage
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    monkeypatch.setattr(coverage, "check_media",
                        lambda *a, **k: coverage.CoverageReport(10.0, 5.0, 0.0))
    ctx = SimpleNamespace(segments=[{"text": "a", "start": 0, "end": 1}], video_path=str(media),
                          preview_path=None, verified_quiet=[], transcript_coverage=None,
                          proofread_failed_ranges=[[0, 50]])
    result = SubtitleCoverageCheck().analyze(ctx)
    assert result["blocking"] is True
    assert any("未校閲" in f for f in result["feedback"])


@pytest.mark.parametrize("orig,new,ok", [
    ("います。", "では記念すべき第1回めのゲストは日本デザイン", False),   # 番号ずれ（実走）
    ("こんにちは。もう初会ね。読んでいただいて。", "こんにちは。もう初回ね。呼んでいただいて。", True),
    ("えー、あの、そうですね", "そうですね", True),
    ("先生どうぞよろしく", "先生、どうぞよろしく。", True),
])
def test_proofread_rejects_text_from_another_line(orig, new, ok):
    from subtitle_engine.ai_proofreader import _plausible_correction
    assert _plausible_correction(orig, new) is ok


def test_flash_caption_is_merged_into_neighbour():
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 2.0, "text": "お腹が"},
             {"start": 2.07, "end": 2.4, "text": "すくようになった"},
             {"start": 3.5, "end": 5.0, "text": "次の文"}]
    n = sync._merge_flashes(items, 0.8)
    assert n == 1 and items[0]["text"] == "お腹が\nすくようになった" and items[0]["end"] == 2.4


def test_punctuation_only_caption_is_dropped():
    out = tf.format_segments([{"text": "。", "start": 0.0, "end": 1.0},
                              {"text": "次です。", "start": 1.0, "end": 2.0}], 15)
    if tf._strip_punctuation_enabled():
        assert [s["text"] for s in out] == ["次です"]


def test_flash_caption_is_rewrapped_into_a_two_line_neighbour():
    # 実例（2分36秒）: 「もう強烈な」が 0.49 秒で消えた。隣は2行なので行として足せなかった。
    # 2つを続けて1枚（2行・1行18字）に組み直せるなら、そうする
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 0.4, "text": "もう強烈な"},
             {"start": 0.47, "end": 3.5, "text": "それのが\n良かったんじゃないですか？"}]
    n = sync._merge_flashes(items, 0.8, max_chars=18, max_lines=2)
    assert n == 1
    text = items[1]["text"]
    assert text.replace("\n", "").replace("\u3000", "") == "もう強烈なそれのが良かったんじゃないですか？"
    assert text.count("\n") <= 1 and all(len(line) <= 18 for line in text.split("\n"))
    assert items[1]["start"] == 0.0


def test_flash_caption_that_does_not_fit_stays():
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 0.4, "text": "知って初めて書く"},
             {"start": 0.47, "end": 3.5,
              "text": "だからもう頭の中は整理できてるから\n書くのは30分か40分か"}]
    assert sync._merge_flashes(items, 0.8, max_chars=18, max_lines=2) == 0


def test_a_long_caption_shown_too_briefly_to_read_is_merged():
    # 実例（2分41秒）: 16 字の「行かなくなったってことはないんで」が 0.76 秒で消えた
    from subtitle_engine import sync
    items = [{"start": 156.82, "end": 161.17, "text": "そういう\nもっと嫌な思いして次の週から"},
             {"start": 161.24, "end": 162.0, "text": "行かなくなったってことはないんで"},
             {"start": 162.14, "end": 163.9, "text": "克服しようと"}]
    assert sync._merge_flashes(items, 0.8, max_chars=18, max_lines=2) == 1
    assert items[0]["text"] == "そういうもっと嫌な思いして次の週から\n行かなくなったってことはないんで"
    assert items[0]["end"] == 162.0


def test_a_short_word_shown_briefly_is_left_alone():
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 2.0, "text": "そうなんですよ"},
             {"start": 2.07, "end": 2.72, "text": "はい"},
             {"start": 2.8, "end": 5.0, "text": "次の文"}]
    assert sync._merge_flashes(items, 0.8, max_chars=18, max_lines=2) == 0


def _marks(text, start, step=0.2):
    from subtitle_engine import aligner
    return [(k, round(start + k * step, 3)) for k in range(len(aligner._norm_text(text)))]


def test_a_flash_that_cannot_be_merged_takes_the_end_of_the_previous_caption():
    # 実例（62秒）: 「理事長で|いらっしゃいまして」と切れ、早口の「いらっしゃいまして」が 0.7 秒で
    # 消えた。隣はどちらも2行で、まとめられない。前の字幕の終わりの文節を、認識の時刻で移す
    from subtitle_engine import sync
    prev = "そして　一般社団法人\n日本デザイン書道作家協会の理事長で"
    items = [{"start": 56.88, "end": 62.58, "text": prev, "_asr": True, "sourceStart": 60.0,
              "_asr_marks": _marks(prev, 56.9)},
             {"start": 62.65, "end": 63.35, "text": "いらっしゃいまして", "_asr": True, "sourceStart": 60.0},
             {"start": 63.42, "end": 68.62,
              "text": "著者としても筆文字デザインの書籍が\n多数おありだということなんですが", "_asr": True}]
    assert sync._resplit_flashes(items, 0.8, max_chars=18, max_lines=2) == 1
    assert items[0]["text"].replace("\n", "") == "そして　一般社団法人日本デザイン書道作家協会の"
    assert items[1]["text"] == "理事長でいらっしゃいまして"
    assert items[1]["start"] == pytest.approx(56.9 + 22 * 0.2)
    assert items[0]["end"] < items[1]["start"]
    assert items[1]["end"] - items[1]["start"] >= 0.8


def test_moved_words_carry_their_times():
    # 切れ目を動かしたら、文字ごとの時刻も一緒に移す（短い字幕が続くと、次の切り直しが
    # ずれた番号で時刻を引いてしまう）
    from subtitle_engine import sync
    prev = "そして　一般社団法人\n日本デザイン書道作家協会の理事長で"
    flash = "いらっしゃいまして"
    items = [{"start": 56.88, "end": 62.58, "text": prev, "_asr": True, "sourceStart": 60.0,
              "_asr_marks": _marks(prev, 56.9)},
             {"start": 62.65, "end": 63.35, "text": flash, "_asr": True, "sourceStart": 60.0,
              "_asr_marks": _marks(flash, 62.65, 0.07)}]
    assert sync._resplit_flashes(items, 0.8, max_chars=18, max_lines=2) == 1
    head, tail = dict(items[0]["_asr_marks"]), dict(items[1]["_asr_marks"])
    assert max(head) == 21  # 「協会の」まで
    assert tail[0] == pytest.approx(56.9 + 22 * 0.2)  # 移した「理」
    assert tail[4] == pytest.approx(62.65)  # もとの「い」
    assert len(tail) == 4 + 9


def test_words_moved_from_another_utterance_are_spaced():
    # 実例（24分41秒）: 「座右の銘って僕ないんだけどね」（ゲスト）の後の「座右の銘じゃなくてもいいんです」
    # （聞き手）が 0.8 秒で消えた。別の発話から移した語との間は1字空ける
    from subtitle_engine import sync
    prev = "いや\u3000それがね\u3000できて\n座右の銘って僕ないんだけどね"
    items = [{"start": 1480.34, "end": 1483.12, "text": prev, "_asr": True, "sourceStart": 1700.0,
              "_asr_marks": _marks(prev, 1480.4, 0.12)},
             {"start": 1483.19, "end": 1483.99, "text": "座右の銘じゃなくてもいいんです", "_asr": True,
              "sourceStart": 1703.5}]
    assert sync._resplit_flashes(items, 0.8, max_chars=18, max_lines=2) == 1
    # 空けた所は、行の途中なら全角スペース、行の境なら改行で残る
    assert "\u3000座右の銘じゃなくても" in sync._flat(items[1])
    assert items[1]["end"] - items[1]["start"] >= 0.8


def test_a_moved_phrase_keeps_the_sentence_breaks_it_had():
    # 実例（15分59秒・28回目）: 「…みんな見てるでしょ。」の「見てるでしょ」を、次の「そう、すごく人気だと
    # 思います」（2行）の頭に移したら、外した句読点の跡がどちらも詰まり「見てるでしょそうすごく人気だと」になった
    from subtitle_engine import sync
    prev = "ドラマというかそのアニメのテレビの\n方でもおそらってみんな見てるでしょ"
    items = [{"start": 955.25, "end": 959.6, "text": prev, "_asr": True, "sourceStart": 1006.0,
              "_ends_punct": True, "_asr_marks": _marks(prev, 955.3, 0.12)},
             {"start": 959.67, "end": 960.4, "text": "そう\nすごく人気だと思います", "_asr": True,
              "sourceStart": 1006.0, "_break_punct": True}]
    assert sync._resplit_flashes(items, 0.8, max_chars=18, max_lines=2) == 1
    assert sync._flat(items[1]) == "見てるでしょ　そう　すごく人気だと思います"
    # 外した句読点の所で折る（「…すごく人気だと|思います」と折らない）
    assert items[1]["text"].split("\n")[-1] != "思います"


def test_a_merged_two_line_caption_keeps_its_sentence_break():
    # 2行の字幕と組み直すときも、句読点を外した跡の改行は語の切れ目として残す
    from subtitle_engine import sync
    items = [{"start": 0.0, "end": 2.5, "text": "見てるでしょ\nすごく人気だと思います", "_break_punct": True},
             {"start": 2.57, "end": 2.9, "text": "だから"}]
    assert sync._merge_flashes(items, 0.8, max_chars=18, max_lines=2) == 1
    assert sync._flat(items[0]) == "見てるでしょ　すごく人気だと思います　だから"


def test_an_unheard_flash_is_not_resplit():
    # カットで声が消えた言葉（9分39秒の「いたんだよね」）は延ばさない
    from subtitle_engine import sync
    prev = "担当とかこう広告担当があって\nスタッフ集まったら30人以上"
    items = [{"start": 572.67, "end": 576.7, "text": prev, "_asr": True,
              "_asr_marks": _marks(prev, 572.7)},
             {"start": 576.77, "end": 577.03, "text": "いたんだよね", "_asr_interp": True}]
    assert sync._resplit_flashes(items, 0.8, max_chars=18, max_lines=2) == 0


def test_a_flash_after_a_long_pause_is_not_resplit():
    from subtitle_engine import sync
    prev = "はい　これからも\nどうぞよろしくお願いいたします"
    items = [{"start": 2250.24, "end": 2253.76, "text": prev, "_asr": True,
              "_asr_marks": _marks(prev, 2250.3)},
             {"start": 2257.66, "end": 2257.99, "text": "はい\nどうもありがとうございました", "_asr": True}]
    assert sync._resplit_flashes(items, 0.8, max_chars=18, max_lines=2) == 0


@pytest.mark.parametrize("orig,new,neighbours,ok", [
    # かなだけの行を漢字に直すのは変換の直し（2026-10-06 実走で「単純」を捨てていた）
    ("たんじゅ、たんじゅ。", "単純、単純。", (), True),
    # ただし隣の行の文なら番号ずれ
    ("います。", "では記念すべき第1回めのゲストは日本デザイン", ("", "では記念すべき第1回目のゲストは日本デザイン"), False),
    ("たんじゅ、たんじゅ。", "記念すべき第一回目", ("記念すべき第一回目のゲスト", ""), False),
    # 漢字を含む行を別の文にするのは、これまでどおり捨てる
    ("新版画賞と、あと 2 日後これ工事って言", "新版画賞と、あと二兎を追う者は一兎をも得", (), False),
])
def test_kana_line_may_be_converted_to_kanji(orig, new, neighbours, ok):
    from subtitle_engine.ai_proofreader import _plausible_correction
    assert _plausible_correction(orig, new, neighbours) is ok


def test_echo_of_a_word_cut_by_the_chunk_boundary_is_dropped():
    # 実例（30 秒）: 30 秒ごとに切って起こすと、境目をまたいだ「まいります」の尻尾が
    # 次の区切りの頭に「います。」として残り、「では」の所に字幕が出た
    from subtitle_engine import gemini_transcriber as gt
    segs = [{"start": 23.1, "end": 29.8, "text": "皆さまにお届けしてまいります。"},
            {"start": 30.0, "end": 31.2, "text": "います。"},
            {"start": 31.2, "end": 43.7, "text": "では記念すべき"}]
    assert [s["text"] for s in gt.drop_boundary_echoes(segs, 30)] == [
        "皆さまにお届けしてまいります。", "では記念すべき"]


def test_segment_at_a_boundary_that_is_not_an_echo_stays():
    from subtitle_engine import gemini_transcriber as gt
    segs = [{"start": 23.1, "end": 29.8, "text": "はい。"},
            {"start": 30.0, "end": 31.2, "text": "います。"},
            {"start": 40.0, "end": 41.0, "text": "はい。"}]
    assert len(gt.drop_boundary_echoes(segs, 30)) == 3


def test_shifted_line_is_never_rescued_by_the_referee():
    from subtitle_engine.ai_proofreader import _correction_verdict
    assert _correction_verdict("います。", "では記念すべき第1回めのゲストは日本デザイン",
                               ["", "では記念すべき第1回目のゲストは日本デザイン"]) == "shifted"
    assert _correction_verdict("歌詞織 です ギャラ は", "菓子折り、ギャラは", []) == "dissimilar"
    assert _correction_verdict("もう初会ね", "もう初回ね", []) == "ok"


@pytest.mark.parametrize("orig,new,want", [
    # 実例（2分37秒・28回目）: 校閲は声を聞いていないのに、相づちの字を書き換えた
    ("ああ、強烈な。", "あお、強烈な。", "ああ、強烈な。"),
    ("ええ、そうです。", "はい、そうです。", "ええ、そうです。"),
    # 消す（フィラーを外す）・漢字にする・句の外を直すのは残す
    ("ああ、強烈な。", "強烈な。", "強烈な。"),
    ("すし、おいしい", "寿司、おいしい", "寿司、おいしい"),
    ("うん、もう初会ね", "うん、もう初回ね", "うん、もう初回ね"),
    # 長い句の中の1字（助詞など）は文脈で決まることがあるので触らない
    ("わたしがいくよ", "わたしはいくよ", "わたしはいくよ"),
])
def test_proofreader_does_not_rewrite_a_short_kana_interjection(orig, new, want):
    from subtitle_engine.ai_proofreader import keep_short_kana_phrases
    assert keep_short_kana_phrases(orig, new) == want


@pytest.mark.parametrize("text,want", [
    # 実例（1分50秒・28回目）: 「駄菓子屋かなんか」の「なんか」を消して「駄菓子屋か行ってる」になった
    ("駄菓子屋かなんか行ってる場合じゃないや", "駄菓子屋かなんか行ってる場合じゃないや"),
    ("15万枚中国なんかな", "15万枚中国なんかな"),
    # 「もうちょっと」「ちょっと待って」の「ちょっと」は中身（「もうチョイスが」・「待って」になった）
    ("もうちょっとチョイスが多い", "もうちょっとチョイスが多い"),
    ("ちょっと待って", "ちょっと待って"),
    # 伸ばす言いよどみは今までどおり外す
    ("えーと先生がこれから", "先生がこれから"),
    ("あのー僕気づいた", "僕気づいた"),
])
def test_filler_removal_keeps_words_that_carry_meaning(text, want):
    assert tf.remove_fillers(text) == want


@pytest.mark.parametrize("text,want", [
    # 30回目の実例: 言いよどみの「なんか」が文中に約20か所出た（「、」で挟まれていない）
    ("すごくなんか真剣さが伝わってくるんだよね。", "すごく真剣さが伝わってくるんだよね。"),
    ("教わる立場だからなんか先生って言われるとなんか偉そうじゃない。",
     "教わる立場だから先生って言われると偉そうじゃない。"),
    ("うん。なんかやはりそういう日本の文化である", "うん。やはりそういう日本の文化である"),
    ("いう形でね、なんかこう、筆文字が", "いう形でね、こう、筆文字が"),
    ("そういうもんのなんか、驚いたことですかね。", "そういうもんの驚いたことですかね。"),
    ("なんかちょっと企んでる", "ちょっと企んでる"),
    # 名詞や「か」のすぐ後ろは「〜など・〜か何か」の意味（1分50秒・9分45秒・13分55秒）
    ("駄菓子屋かなんか行ってる場合じゃないや", "駄菓子屋かなんか行ってる場合じゃないや"),
    ("広報担当なんかが、スタッフ入れたら", "広報担当なんかが、スタッフ入れたら"),
    ("15万枚中国なんかな。", "15万枚中国なんかな。"),
    ("シャープなんかも", "シャープなんかも"),
    # 外すと助詞だけが残るときは外さない（相づちだけの字幕の規則に任せる）
    ("なんかさ、", "なんかさ、"),
])
def test_filler_nanka_is_removed_unless_it_follows_a_noun(text, want):
    assert tf.strip_context_fillers(text, ["なんか"]) == want


def test_trailing_filler_words_do_not_stay_at_the_end_of_a_caption():
    # 30回目の 37分49秒: 「…考えると、なんかちょっと、」の言い差しが「…考えると\nなんかちょっと」で出た
    out = tf.format_segments([{"text": "ああ、筆に頼るっていうことを考えると、なんかちょっと、",
                               "start": 0.0, "end": 3.0}], 18)
    assert ["".join(s["text"].split()) for s in out] == ["ああ筆に頼るっていうことを考えると"]
    # 「、」で挟まれていない「ちょっと」は中身なので残す
    [kept] = tf.format_segments([{"text": "遊郭とか、ちょっと詳しくないんだけど。", "start": 0.0, "end": 3.0}], 18)
    assert "ちょっと" in kept["text"]


def test_lead_word_at_the_head_of_a_later_caption_is_removed():
    # 実例（39分17秒）: 「…思ってるところで、じゃあ筆が本当に入ってこなかったら…」を
    # 分けた2枚目が「じゃあ筆が」で始まった
    text = "で、ちょっと大変なことになるなって思ってるところで、じゃあ筆が本当に入ってこなかったら、筆作ろうかなみたいな。"
    out = tf.format_segments([{"text": text, "start": 0.0, "end": 8.0}], 18)
    assert out and not any(s["text"].startswith("じゃあ") for s in out)


@pytest.mark.parametrize("text,expected", [
    ("あの", True),
    ("えー、あの。", True),
    ("えっと", True),
    ("あの映画のタイトル", False),
])
def test_filler_only_caption_is_not_shown(text, expected):
    # 実例（4分02秒）: 「あの」だけの字幕が 0.9 秒出た。音声認識にも聞こえていない
    from template_constants import _DEFAULT_SUBTITLE_RULES as rules
    assert tf.is_standalone_omittable(text, rules["omit_standalone_words"]) is expected


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_a_lone_kanji_is_not_split_from_its_compound():
    # 実例（56 秒）: BudouX が「一般社団法人」を「一般社団法｜人」と分け、
    # 行の折り目が「一般社団法\n人日本デザイン…」になった
    caps = tf.split_into_captions(
        "を主宰されていて、そして、一般社団法人日本デザイン書道作家協会の理事長で", 18, 2)
    lines = [line for c in caps for line in c.split("\n")]
    assert not any(line.startswith("人") for line in lines)
    assert any("一般社団法人" in line for line in lines)


def test_line_length_check_follows_the_formatters_line_width():
    # 1行 18 字に広げた（2026-10-06 ユーザー了承）のに、品質ゲートはテンプレートが無いと
    # 放送の 15 字で測り、整形どおりの字幕で毎回 5 点引いていた
    from quality_gate_plugins import SubtitleLineCheck
    from template_constants import _DEFAULT_SUBTITLE_RULES as rules
    width = rules["max_chars_per_line"]
    ok = SimpleNamespace(segments=[{"text": "あ" * width} for _ in range(5)])
    long = SimpleNamespace(segments=[{"text": "あ" * (width + 1)} for _ in range(5)])
    assert SubtitleLineCheck().analyze(ok)["deductions"] == 0
    assert SubtitleLineCheck().analyze(long)["deductions"] == 5


def test_word_spaced_transcript_is_joined():
    # 実例（31 分〜）: 起こし直した区切りが「久田 先生 って 普段 どんな 人 な ん だろ うっ て」と
    # 語ごとに空白で区切って返り、校閲が空白を詰めなかった回は字幕に「人 な\nん だろ うっ て」と出た
    from subtitle_engine import gemini_transcriber as gt
    segs = [{"start": 0.0, "end": 2.0, "text": "さん 、 久田 先生 って 普段 どんな 人 な ん だろ うっ て 、"},
            {"start": 2.0, "end": 3.0, "text": "オフ の 人 か は 何 し てる ん です か ?"},
            {"start": 3.0, "end": 4.0, "text": "YouTube の チャンネル"},
            # 77 秒の実例: 数字の両側の空白が残り、字幕に「小学校 3 年生」と出た
            {"start": 4.0, "end": 6.0, "text": "私 は あの 、 小 学校 3 年 生 の 時 に"},
            {"start": 6.0, "end": 7.0, "text": "僕 が 入っ て 23 ぐらい の 時 かな"}]
    out = gt.join_spaced_words(segs)
    assert out[0]["text"] == "さん、久田先生って普段どんな人なんだろうって、"
    assert out[1]["text"] == "オフの人かは何してるんですか?"
    assert out[2]["text"] == "YouTube のチャンネル"
    assert out[3]["text"] == "私はあの、小学校3年生の時に"
    assert out[4]["text"] == "僕が入って23ぐらいの時かな"
    assert segs[0]["text"].startswith("さん 、")  # 元のリストは書き換えない


def test_particle_left_at_the_head_of_the_next_segment_goes_back():
    # 実例（56 秒）: 30 秒ごとの起こしの区切りで「…久木田デザイン書道塾」「を主宰されていて、そして、…」と
    # 割れ、字幕が「を主宰されていて」で始まった。「を」「に」は文の頭に来ない
    segs = [{"start": 50.0, "end": 60.0, "text": "先生はアドシアター代表で久木田デザイン書道塾"},
            {"start": 60.0, "end": 67.0, "text": "を主宰されていて、そして、一般社団法人の理事長で"}]
    out = tf.format_segments(segs, 18)
    texts = [s["text"].replace("\n", "") for s in out]
    assert not any(t.startswith("を") for t in texts)
    assert any(t.endswith("書道塾を主宰されていて") for t in texts)


def test_a_segment_after_a_full_stop_keeps_its_head():
    segs = [{"start": 0.0, "end": 2.0, "text": "そうなんです。"},
            {"start": 2.0, "end": 4.0, "text": "にこにこしてました"}]
    out = tf.format_segments(segs, 18)
    assert [s["text"] for s in out] == ["そうなんです", "にこにこしてました"]


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
@pytest.mark.parametrize("prev,cur,joined,bad_head", [
    # 29分の実例: 間を置いて「私が手がけた仕事」「を深掘りして」と2つに起こされた（読点なし）
    ("私が手がけた仕事", "を深掘りして", "私が手がけた仕事を深掘りして", "を"),
    # 13分の実例: 「…中国は取れる」「とかがあったんで、使えないんですよ」
    ("日本は取れない言葉だけど、中国は取れる", "とかがあったんで、使えないんですよ",
     "中国は取れるとかがあったんで", "とかが"),
    # 13分の実例: 「あと」「は」が語の途中で割れた
    ("ね、コラボしたりとかあと", "はちょっと有名なフォントがあるじゃないですか、先生。",
     "コラボしたりとかあとは", "はちょっと"),
])
def test_a_segment_that_continues_the_previous_phrase_goes_back(prev, cur, joined, bad_head):
    segs = [{"start": 0.0, "end": 4.0, "text": prev}, {"start": 4.5, "end": 9.0, "text": cur}]
    texts = [s["text"].replace("\n", "") for s in tf.format_segments(segs, 18)]
    assert any(joined in t for t in texts)
    assert not any(t.startswith(bad_head) for t in texts)


def test_a_segment_starting_with_a_small_kana_joins_the_previous_sentence():
    # 37分の実例: 「魚の市場。もう口すごい。」「っていうことですかね。…」。「っ」で始まる語は無い
    segs = [{"start": 0.0, "end": 3.0, "text": "魚の市場。もう口すごい。"},
            {"start": 3.0, "end": 8.0, "text": "っていうことですかね。もお料理好きの皆さんびっくりですよね。"}]
    texts = [s["text"].replace("\n", "") for s in tf.format_segments(segs, 18)]
    assert not any(t.startswith("っ") for t in texts)
    assert any("もう口すごいっていうことですかね" in t for t in texts)


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
@pytest.mark.parametrize("prev,cur", [
    ("そうなんです", "にこにこしてました"),
    ("すごいですね", "はい、そうです"),
    ("これは", "はい、そうです"),
    ("本当にすごい", "もう終わりです"),
    ("昔はね", "コピーライターのことを"),
])
def test_a_segment_that_starts_a_new_phrase_keeps_its_head(prev, cur):
    segs = [{"start": 0.0, "end": 2.0, "text": prev}, {"start": 2.5, "end": 5.0, "text": cur}]
    texts = [s["text"] for s in tf.format_segments(segs, 18)]
    assert texts == [tf.strip_punctuation(prev), tf.strip_punctuation(cur)]


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_a_whole_segment_moved_back_keeps_its_end_time():
    segs = [{"start": 10.0, "end": 13.6, "text": "私が手がけた仕事"},
            {"start": 14.1, "end": 15.7, "text": "を深掘りして"}]
    out = tf.format_segments(segs, 18)
    assert [s["text"] for s in out] == ["私が手がけた仕事を深掘りして"]
    assert out[0]["start"] == 10.0 and out[0]["end"] >= 15.7


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_no_line_is_left_with_one_or_two_characters():
    # 7分45秒の実例: 「が、もう1個…」が「が」だけの1行と残りに折られた
    out = tf.split_into_captions("が、もう1個別のを言うじゃないですかって思ったんですよ。", 18, 2)
    lines = [ln for c in out for ln in tf.strip_punctuation(c).split("\n")]
    assert all(len(ln) > 2 for ln in lines), lines


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_punctuation_that_will_be_removed_does_not_count_toward_the_line():
    # 37分の実例: 見える字は18字なのに、消える「。」まで数えて「も」/「お料理…」に折った
    out = tf.format_segments([{"start": 0.0, "end": 4.0, "text": "もお料理好きの皆さんびっくりですよね。"}], 18)
    assert [s["text"] for s in out] == ["もお料理好きの皆さんびっくりですよね"]


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
@pytest.mark.parametrize("stop", ["、", "。"])
def test_a_title_split_from_the_name_goes_back(stop):
    # 56 秒の実例: 「…久木田デザイン書道塾」「主宰、そして、一般社団法人…」と割れ、字幕が「主宰」で始まった。
    # 起こしの「ましょう。」を校閲が「主宰。」に直した回は、「主宰」だけの字幕が 0.8 秒出た
    segs = [{"start": 50.0, "end": 60.0, "text": "先生は株式会社アドシアター代表で久木田デザイン書道塾"},
            {"start": 60.0, "end": 67.0, "text": f"主宰{stop}そして、一般社団法人日本デザイン書道作家協会の理事長でいらっしゃいまして、"}]
    texts = [s["text"].replace("\n", "") for s in tf.format_segments(segs, 18)]
    assert any("久木田デザイン書道塾主宰" in t for t in texts)
    assert not any(t.startswith("主宰") for t in texts)


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_nouns_next_to_each_other_without_a_comma_stay_apart():
    segs = [{"start": 0.0, "end": 1.0, "text": "東京"}, {"start": 1.5, "end": 4.0, "text": "大阪に行きました"}]
    assert [s["text"] for s in tf.format_segments(segs, 18)] == ["東京", "大阪に行きました"]


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_a_particle_the_previous_segment_already_has_is_not_doubled():
    # 13 分 43 秒の実例: 校閲が前の「…とかあと」を「…とかあとは」に直し、後ろに「は有名な…」が残った。
    # 頭を前に戻すと「あとはは」になった
    segs = [{"start": 0.0, "end": 2.0, "text": "ね、コラボしたりとかあとは"},
            {"start": 2.0, "end": 5.0, "text": "は有名なフォントがあるじゃないですか、先生。"}]
    texts = [s["text"].replace("\n", "") for s in tf.format_segments(segs, 18)]
    assert not any("あとはは" in t for t in texts)
    assert not any(t.startswith("は有名") for t in texts)
    assert any(t.endswith("コラボしたりとかあとは") for t in texts)


def _junctions(captions):
    """字幕の切れ目と行の折り目の前後（前の行, 次の行）を、句読点を外した形で並べる。"""
    lines = [ln for c in captions for ln in tf.strip_punctuation(c).split("\n")]
    return list(zip(lines, lines[1:]))


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
@pytest.mark.parametrize("text,head,helper", [
    # 26回目の 27 秒: 「…お届けして」と「まいります」が別の字幕になり、「まいります」が 0.8 秒だけ出た
    ("手書きの文字に込められた人生観や書道の魅力を皆様にお届けしてまいります。", "お届けして", "まいります"),
    # 61 秒: 「…理事長で」と「いらっしゃいまして」が別の字幕になった
    ("一般社団法人日本デザイン書道作家協会の理事長でいらっしゃいまして、", "理事長で", "いらっしゃいまして"),
    ("大切にされている言葉をこれから先生に書いていただきます。", "書いて", "いただきます"),
    ("今でもその当時の教室のことをはっきりと覚えております。", "覚えて", "おります"),
])
def test_a_helper_verb_stays_with_the_verb_it_helps(text, head, helper):
    # 「て・で」の後ろの補助の動詞（まいる・いらっしゃる・いただく・おる）は前の動詞とひと塊。
    # 字幕の切れ目でも行の折り目でも、そこでは割らない
    caps = tf.split_into_captions(text, 18, 2, trim=True)
    assert not any(a.endswith(head) and b.startswith(helper) for a, b in _junctions(caps)), caps


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_the_quoting_tte_stays_with_iu():
    # 76 秒: 「…出会ったきっかけって」/「いうのは…」と折れた
    caps = tf.split_into_captions("最初に書に出会ったきっかけっていうのはなんかありますでしょうか？", 18, 2, trim=True)
    assert not any(a.endswith("って") and b.startswith("いう") for a, b in _junctions(caps)), caps


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_te_followed_by_a_new_verb_may_still_be_split():
    # 補助の動詞でなければ「て」の後ろは切ってよい所のまま（「書いて、/送ってくれた」）
    assert tf._break_score("書いて", "送ってくれた") > 0
    assert tf._break_score("お届けして", "まいります。") < 0



@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
@pytest.mark.parametrize("prev,cur,joined,bad_head", [
    # 26回目の 2分55秒: 「…もう行かないってなりそう」「ですよね/平気でしょね」と字幕が「ですよね」で始まった
    ("普通だったらもう行かないってなりそう", "ですよね。平気でしょね。", "行かないってなりそうですよね", "ですよね"),
    # 締め（39分53秒）: 校閲が「お越しいただい」「いただきました。」の重なりを「いただき」「ました。」に直し、
    # 字幕が「ました　ありがとうございました」で始まった
    ("本日は久木田博信先生にお越しいただき", "ました。ありがとうございました。",
     "お越しいただきました", "ました"),
])
def test_a_polite_ending_left_at_the_head_goes_back_to_its_verb(prev, cur, joined, bad_head):
    # 「です・ます」（＋「ね・よ」）は文を始められない。前の述語に戻す
    segs = [{"start": 0.0, "end": 4.0, "text": prev}, {"start": 4.1, "end": 7.0, "text": cur}]
    texts = [s["text"].replace("\n", "") for s in tf.format_segments(segs, 18)]
    assert any(joined in t for t in texts), texts
    assert not any(t.startswith(bad_head) for t in texts), texts


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
@pytest.mark.parametrize("prev,cur", [
    ("そうなんです", "ですから、私はこう思います"),
    ("本当に", "ますます良くなりました"),
])
def test_words_that_merely_start_like_a_polite_ending_keep_their_place(prev, cur):
    segs = [{"start": 0.0, "end": 2.0, "text": prev}, {"start": 2.5, "end": 5.0, "text": cur}]
    texts = [s["text"] for s in tf.format_segments(segs, 18)]
    assert texts == [tf.strip_punctuation(prev), tf.strip_punctuation(cur)]


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_a_verb_cut_after_its_small_tsu_is_not_split():
    # 26回目の 1分57秒: 「母親に　僕も習字入れ入っ」「てへえ/言って…」。「っ」で終わる動詞は
    # 後ろの「て・た」と1語なので、字幕の切れ目にしない
    segs = [{"start": 127.5, "end": 131.5, "text": "母親に、僕も習字入れ入っ"},
            {"start": 131.5, "end": 138.5, "text": "てへえ。言って、それが、それが8歳です。"}]
    texts = [s["text"].replace("\n", "") for s in tf.format_segments(segs, 18)]
    assert not any(t.endswith("っ") for t in texts), texts
    assert not any(t.startswith("て") for t in texts), texts
    assert any("入って" in t for t in texts), texts


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
@pytest.mark.parametrize("prev,cur", [
    ("えっ", "それは本当ですか"),
    ("あっ", "そうなんですね"),
])
def test_an_exclamation_ending_in_small_tsu_keeps_its_own_caption(prev, cur):
    segs = [{"start": 0.0, "end": 1.0, "text": prev}, {"start": 1.5, "end": 4.0, "text": cur}]
    assert [s["text"] for s in tf.format_segments(segs, 18)] == [prev, cur]


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_a_word_cut_short_and_said_again_is_shown_once():
    # 締め（43分9秒・起こしの区切り）: 前の区切りが語を「お越しいただい」と補い、次の区切りが
    # 「いただきました。」と頭から起こした。字幕は「…お越しいただい」「いただきました…」になる
    segs = [{"start": 2582.2, "end": 2589.2,
             "text": "はい、今日はありがとうございました。本日は久木田博信先生にお越しいただい"},
            {"start": 2589.4, "end": 2591.4, "text": "いただきました。ありがとうございました。"}]
    texts = [s["text"].replace("\n", "") for s in tf.format_segments(segs, 18)]
    joined = "".join(texts)
    assert "お越しいただきました" in joined, texts
    assert "いただいいただ" not in joined and "いただい" not in joined, texts
    assert not any(t.startswith("いただき") for t in texts), texts


@pytest.mark.skipif(tf._phrase_parser() is None, reason="BudouX が無い")
def test_a_thank_you_said_by_both_after_a_full_stop_is_kept_twice():
    segs = [{"start": 0.0, "end": 2.0, "text": "ありがとうございました。"},
            {"start": 2.0, "end": 4.0, "text": "ありがとうございました。"}]
    assert [s["text"] for s in tf.format_segments(segs, 18)] == ["ありがとうございました"] * 2



def test_an_unheard_caption_too_fast_to_read_is_not_shown():
    # 26回目の 3分10秒: 認識に声の無い「何か一番最初のきっかけなんですね」（16 字）が、聞こえた字幕の
    # 間に 0.55 秒だけ出た。読めず、声も確かめられない。0.5 秒を超えるので消す対象から漏れていた
    # （全編で 13 枚・締めの最後の「ありがとうございました」0.58 秒も）
    from subtitle_engine import sync
    items = [{"start": 188.56, "end": 189.85, "text": "そうですね", "_asr": True},
             {"start": 190.27, "end": 190.82, "text": "何か一番最初のきっかけなんですね", "_asr_interp": True},
             {"start": 190.89, "end": 196.29, "text": "ぼくはね　中学校に入ってね\nバスケットボール部に", "_asr": True}]
    assert sync._drop_unheard_flashes(items, 0.8) == 1
    assert items[1].get("_merged") and not items[0].get("_merged") and not items[2].get("_merged")


def test_an_unheard_word_that_can_be_read_in_time_stays():
    from subtitle_engine import sync
    items = [{"start": 10.0, "end": 10.7, "text": "はい", "_asr_interp": True},
             {"start": 12.0, "end": 12.6, "text": "そうなんですよ", "_asr": True, "_asr_first": 12.0}]
    assert sync._drop_unheard_flashes(items, 0.8) == 0
