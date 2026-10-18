"""字幕のレビュー画面の控えと、画面で付けた印から校正台帳の直しを作る（2026-10-17）。

北原さんは 52回目の 18分までを見て、14か所を「時刻・誤り→正しい字」の文で伝えた。全 43分を同じように
伝えるのは手間なので、画面で印を付けて正しい字を書き、それを台帳に入れる。
"""
import json

from subtitle_engine import review_ledger, review_sheet

SIDECAR = {
    "segments": [
        {"start": 0.36, "end": 3.2, "text": "こんにちは　書家の北原美麗です"},
        {"start": 216.0, "end": 218.0, "text": "つないだ所をまたぐ字幕"},
    ],
    "ranges": [[1.4, 217.99], [218.62, 351.01]],
}


def test_output_seconds_go_back_to_the_source_through_the_cut_ranges():
    ranges = SIDECAR["ranges"]
    assert review_sheet.source_time(0.0, ranges) == 1.4
    assert review_sheet.source_time(216.59, ranges) == 217.99
    assert review_sheet.source_time(216.6, ranges) == 218.63


def test_the_sheet_carries_each_caption_with_its_output_and_source_seconds():
    sheet = review_sheet.export(SIDECAR, "r53", "53回目", "raw4_concat_preview_360p.mp4")
    assert sheet["run"] == "r53" and sheet["video"] == "raw4_concat_preview_360p.mp4"
    assert sheet["duration"] == round(216.59 + 132.39, 2)
    first = sheet["captions"][0]
    assert first == {"i": 0, "s": 0.36, "e": 3.2, "src": 3.18, "t": "こんにちは　書家の北原美麗です"}
    # 字幕の真ん中（出来上がりの 217 秒）は、つないだ後ろの素材の秒
    assert sheet["captions"][1]["src"] == 219.03


def _mark(text, fix, t=100.0, src=110.0, state="open", note=""):
    return {"cap": 1, "t": t, "src": src, "text": text, "fix": fix, "state": state, "note": note}


def test_a_mark_becomes_a_correction_of_only_the_changed_words():
    new, rest = review_sheet.to_corrections([_mark("もう照明はカンカン当たってるわ\n暑いわ　焦るわ",
                                                   "もう照明はカンカン当たってるわ\n暑いわ　折れるわ",
                                                   t=707.0, src=711.8)],
                                            by="北原", day="2026-10-18", label="53回目")
    assert rest == []
    assert new == [{"id": "2026-10-18-01", "at": 711.8, "from": "焦るわ", "to": "折れるわ", "by": "北原",
                    "seen": "53回目 11:47"}]


def test_a_short_change_takes_the_neighbouring_words_so_it_lands_in_one_place():
    # 「ね」1字では行のどの「ね」か決まらない。前の塊を「、」でつないで付ける
    new, _ = review_sheet.to_corrections([_mark("それで来年はユネスコ無形文化遺産に\nなるであろうね　ね",
                                               "それで来年はユネスコ無形文化遺産に\nなるであろうね　よ")],
                                         by="北原", day="2026-10-18", label="53回目")
    assert [(c["from"], c["to"]) for c in new] == [("なるであろうね、ね", "なるであろうね、よ")]


def test_a_change_across_a_line_break_keeps_the_punctuation_of_the_line():
    # 「、」の所で改行した字幕。改行をまたいで1組にすると、行の「、」ごと置き換わる
    new, _ = review_sheet.to_corrections([_mark("「新・日本」と\nあと「一日一書」っていうやつを",
                                               "「森羅万象」と\nあと「日々是好日」っていうやつを")],
                                         by="北原", day="2026-10-18", label="53回目")
    assert [(c["from"], c["to"]) for c in new] == [("「新・日本」と", "「森羅万象」と"),
                                                   ("あと「一日一書」って", "あと「日々是好日」って")]
    line = [{"start": 770.0, "end": 775.0, "sourceStart": 770.0, "sourceEnd": 775.0,
             "text": "「新・日本」と、あと「一日一書」っていうやつを、今だったら"}]
    report = review_ledger.apply(line, {"corrections": [{**c, "at": 772.0} for c in new], "glossary": []})
    assert line[0]["text"] == "「森羅万象」と、あと「日々是好日」っていうやつを、今だったら"
    assert len(report["applied"]) == 2


def test_neighbouring_short_changes_become_one_correction_so_neither_undoes_the_other():
    # 短い直しが隣の直した塊を付けると、別々に当てたとき先の直しで後の直しの字が消えて当たらない
    # （53回目 29分10秒「なんと　なん　なん」→「なんと　なんと　皆さん」の「なん、なん」が当たらなかった）
    new, _ = review_sheet.to_corrections([_mark("なんと　なん　なん", "なんと　なんと　皆さん")],
                                         by="北原", day="2026-10-18", label="53回目")
    assert [(c["from"], c["to"]) for c in new] == [("なんと、なん、なん", "なんと、なんと、皆さん")]
    line = [{"start": 1765.0, "end": 1770.0, "sourceStart": 1765.0, "sourceEnd": 1770.0,
             "text": "なんと、なん、なん。あのプレゼント"}]
    report = review_ledger.apply(line, {"corrections": [{**c, "at": 1768.0} for c in new], "glossary": []})
    assert line[0]["text"] == "なんと、なんと、皆さん。あのプレゼント"
    assert report["missing"] == []


def test_a_long_change_next_to_a_short_one_is_written_as_one_correction():
    # 長い直しの塊を、隣の短い直しが付けて使う形も同じ（先に長い直しが当たると、短い直しの字が無くなる）
    new, _ = review_sheet.to_corrections([_mark("横島は横島パンですか　ね", "横浜　ねえ")],
                                         by="北原", day="2026-10-18", label="53回目")
    assert [(c["from"], c["to"]) for c in new] == [("横島は横島パンですか、ね", "横浜、ねえ")]


def test_a_gap_written_into_the_fix_comes_back_as_a_comma_in_the_line():
    # 塊の数が変わる直しは全体を1組にする。塊の切れ目（句読点の跡）は「、」に戻し、直しで足した切れ目も残す
    # （53回目 33分52秒「どうぞどうぞどうぞ」→「そうそう　そうです」が「そうそうそうです」と1語になっていた）
    new, _ = review_sheet.to_corrections([_mark("どうぞどうぞどうぞ", "そうそう　そうです")],
                                         by="北原", day="2026-10-18", label="53回目")
    assert [(c["from"], c["to"]) for c in new] == [("どうぞどうぞどうぞ", "そうそう、そうです")]


def test_digits_and_letters_typed_full_width_are_written_half_width():
    # 「正しくは」は日本語入力で書くので数字が全角になる（59回目の 24分58秒「６日間」）。字幕の数字と英字は
    # 半角（「30本」「Be Original」）なので、直しも半角にそろえる。「？」や全角スペースは字幕の字なので触らない
    new, _ = review_sheet.to_corrections([_mark("一週間筆取らないから", "６日間筆取らないから", t=1498.19, src=1512.91),
                                          _mark("これ何号？　ここ", "これ２９６号？　ここ", src=1937.0),
                                          _mark("エスエヌエスで見た", "ＳＮＳで見た", src=2000.0)],
                                         by="北原", day="2026-10-18", label="59回目")
    assert [(c["from"], c["to"]) for c in new] == [("一週間筆取", "6日間筆取"), ("これ何号？", "これ296号？"),
                                                    ("エスエヌエスで見た", "SNSで見た")]


def test_marks_without_a_written_fix_are_kept_for_a_person_to_read():
    marks = [_mark("ここは合ってる", "", note="音が聞き取れない"),
             _mark("問題なしの印", "問題なしの印を直した", state="ok"),
             _mark("同じ字", "同じ字")]
    new, rest = review_sheet.to_corrections(marks, by="北原", day="2026-10-18", label="53回目")
    assert new == [] and len(rest) == 3


def test_the_ledger_is_written_one_entry_per_line_and_reads_back_the_same(tmp_path):
    data = {"version": 1, "material": {"name": "対談"}, "glossary": [{"term": "剣閃", "wrong": ["剣先"]}],
            "corrections": [{"id": "a", "at": 1.0, "from": "x", "to": "y"}, {"id": "b", "at": 2.0, "from": "p", "to": "q"}]}
    text = review_sheet.dump_ledger(data)
    assert json.loads(text) == data
    assert '    {"id": "a", "at": 1.0, "from": "x", "to": "y"},' in text.splitlines()


def test_importing_marks_appends_corrections_after_the_ones_of_the_same_day(tmp_path, capsys):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"version": 1, "glossary": [], "corrections": [
        {"id": "2026-10-18-01", "at": 5.0, "from": "a", "to": "b"}]}, ensure_ascii=False), encoding="utf-8")
    marks = tmp_path / "marks.json"
    marks.write_text(json.dumps([_mark("で　焦るわけ", "で　折れるわけ", t=561.0, src=561.7)], ensure_ascii=False),
                     encoding="utf-8")
    assert review_sheet.main(["import", str(marks), "--ledger", str(ledger), "--by", "北原",
                              "--day", "2026-10-18", "--label", "53回目"]) == 0
    data = review_ledger.load(ledger)
    assert [c["id"] for c in data["corrections"]] == ["2026-10-18-01", "2026-10-18-02"]
    assert (data["corrections"][1]["from"], data["corrections"][1]["to"]) == ("焦るわけ", "折れるわけ")
    assert "直し 1 件" in capsys.readouterr().out


def test_comparing_a_rebuild_lists_only_the_captions_that_changed(capsys, tmp_path):
    approved = {"segments": [{"start": 0.0, "end": 2.0, "text": "折れるわけ"}, {"start": 2.0, "end": 4.0, "text": "久木田さん"}],
                "ranges": [[561.0, 565.0]]}
    again = {"segments": [{"start": 0.0, "end": 2.0, "text": "折れるわけ"}, {"start": 2.0, "end": 4.0, "text": "藤田さん"}],
             "ranges": [[561.0, 565.0]]}
    assert review_sheet.compare(approved, approved) == []
    assert review_sheet.compare(approved, again) == [{"src": 563.0, "approved": ["久木田さん"], "again": ["藤田さん"]}]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(again, ensure_ascii=False), encoding="utf-8")
    assert review_sheet.main(["compare", str(a), str(b)]) == 1
    assert "違い 1 か所" in capsys.readouterr().out
    assert review_sheet.main(["compare", str(a), str(a)]) == 0
