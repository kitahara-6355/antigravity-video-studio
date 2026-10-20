"""編集の決まり（edit_standards）— 台帳の門と、書き出した字幕の点検。"""
import copy
import json

import pytest

from backend import edit_standards as es


def _side(*segments, cut_points=(), gone=()):
    return {"segments": [dict(start=a, end=b, text=t) for a, b, t in segments],
            "ranges": [[0.0, 100.0]], "cut_points": list(cut_points), "gone": list(gone)}


def test_every_rule_in_the_ledger_still_has_its_code_and_tests():
    assert es.gate(es.load()) == []


def test_every_rule_says_whose_words_it_came_from():
    for rule in es.load()["rules"]:
        assert rule["from"]["said"].strip(), rule["id"]


def test_a_renamed_function_is_caught_by_the_gate():
    ledger = copy.deepcopy(es.load())
    ledger["rules"][0]["where"] = ["backend/subtitle_engine/sync.py::no_such_function"]
    assert any("no_such_function" in p for p in es.gate(ledger))


def test_a_missing_dictionary_key_is_caught_by_the_gate():
    ledger = copy.deepcopy(es.load())
    ledger["rules"][0]["where"] = ["backend/template_constants.py::_DEFAULT_SUBTITLE_RULES.no_such_key"]
    assert any("no_such_key" in p for p in es.gate(ledger))


def test_a_missing_test_and_a_rule_without_tests_are_caught_by_the_gate():
    ledger = copy.deepcopy(es.load())
    ledger["rules"][0]["tests"] = ["backend/tests/test_edit_standards.py::test_that_does_not_exist"]
    ledger["rules"][1]["tests"] = []
    problems = es.gate(ledger)
    assert any("test_that_does_not_exist" in p for p in problems)
    assert any(p.startswith(ledger["rules"][1]["id"]) and "tests が空" in p for p in problems)


def test_a_rule_without_its_origin_is_caught_by_the_gate():
    ledger = copy.deepcopy(es.load())
    ledger["rules"][0]["from"] = {"day": "2026-10-06", "by": "北原", "said": ""}
    assert any("from" in p for p in es.gate(ledger))


def test_punctuation_is_found_but_digit_separators_are_not():
    side = _side((0, 2, "こんにちは、書家です"), (3, 5, "1,000人に教えた"), (6, 8, "2.5倍になった"))
    assert len(es.check_no_punctuation(side)) == 1


def test_filler_only_captions_are_not_checked_because_they_are_not_burned():
    side = _side((0, 0.2, "はい"), (1, 3, "書家の北原です"))
    assert [s["text"] for s in es.shown(side)] == ["書家の北原です"]
    assert es.check_flashes(side) == []


def test_a_line_over_the_limit_and_a_third_line_are_found():
    side = _side((0, 3, "書" * 19), (4, 6, "一行目\n二行目\n三行目"), (7, 9, "書" * 18 + "\n" + "道" * 18))
    assert len(es.check_line_limits(side)) == 2


def test_a_caption_crossing_a_cut_is_found():
    side = _side((0, 3, "カットをまたぐ"), (4, 6, "またがない"), cut_points=[2.0, 6.0])
    assert len(es.check_no_cross_cut(side)) == 1


def test_a_lost_line_with_words_fails_and_a_lost_reply_does_not():
    side = _side((0, 3, "書家の北原です"), (10, 13, "よろしくお願いします"),
                 gone=[{"start": 5, "end": 6, "text": "エピソードなんですか", "reason": "no_room"},
                       {"start": 7, "end": 7.2, "text": "はい", "reason": "no_room"}])
    lost = es.check_no_lost_words(side)
    assert len(lost) == 1 and "エピソード" in lost[0]


def test_a_term_broken_by_a_line_or_between_captions_is_found():
    terms = ["久木田ヒロノブ"]
    assert es.check_terms_unbroken(_side((0, 3, "ゲストの久木田\nヒロノブ先生です")), terms)
    assert es.check_terms_unbroken(_side((0, 3, "ゲストの久木田"), (3, 5, "ヒロノブ先生です")), terms)
    assert es.check_terms_unbroken(_side((0, 3, "ゲストの\n久木田ヒロノブ先生です")), terms) == []


def test_a_long_two_line_caption_is_advisory_only():
    side = _side((0, 8.5, "サザエをとって\n食べて問題ないと"))
    results = [r for r in es.check(side, es.load()) if r["check"] == "long_captions"]
    assert results and results[0]["hits"] and results[0]["advisory"]
    assert all(r["check"] != "long_captions" for r in es.failed(es.check(side, es.load())))


def test_check_exits_1_only_when_a_rule_is_broken(tmp_path, capsys):
    good, bad = tmp_path / "good.subtitles.json", tmp_path / "bad.subtitles.json"
    good.write_text(json.dumps(_side((0, 2, "書家の北原です"))), encoding="utf-8")
    bad.write_text(json.dumps(_side((0, 2, "書家の、北原です"))), encoding="utf-8")
    assert es.main(["--check", str(good)]) == 0
    assert es.main(["--check", str(bad)]) == 1
    assert "S01" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--show", "--gate"])
def test_show_and_gate_run(flag, capsys):
    assert es.main([flag]) == 0
    assert capsys.readouterr().out.strip()
