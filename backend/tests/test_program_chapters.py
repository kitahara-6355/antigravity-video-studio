"""概要欄のチャプターの点検（backend/program_package/chapters.py）。"""
from backend.program_package import chapters as ch


def test_lines_with_a_time_become_chapters():
    text = "▼チャプター\n0:00 オープニング\n1:13 出会い\n1:02:05 エンディング\n#書道"
    assert ch.parse(text) == [(0, "オープニング"), (73, "出会い"), (3725, "エンディング")]


def test_good_chapters_pass():
    assert ch.problems([(0, "a"), (60, "b"), (120, "c")], 200) == []


def test_youtube_rules_are_enforced():
    assert any("3つ以上" in p for p in ch.problems([(0, "a"), (60, "b")], 200))
    assert any("0:00" in p for p in ch.problems([(5, "a"), (60, "b"), (120, "c")], 200))
    assert any("10秒" in p for p in ch.problems([(0, "a"), (5, "b"), (120, "c")], 200))
    assert any("後ろ" in p for p in ch.problems([(0, "a"), (120, "b"), (60, "c")], 200))
    assert any("長さ" in p for p in ch.problems([(0, "a"), (60, "b"), (300, "c")], 200))
