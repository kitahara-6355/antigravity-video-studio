import os
import json
from datetime import datetime, timezone, timedelta
import pytest
from backend.agents.orchestration.link_validator import (
    get_rel_link,
    validate_dashboard_links,
    _record_event_if_changed,
    _record_topic_event,
    _read_recent_events,
)

def test_get_rel_link():
    # 正常系：通常の絶対パス
    path = r"C:\path\to\file.txt"
    link = get_rel_link(path)
    assert link.startswith("file:///")
    assert "C:" in link
    assert "path/to/file.txt" in link

    # スペースや日本語を含むパス
    path_with_space = r"C:\My Folder\テスト.md"
    link_with_space = get_rel_link(path_with_space)
    assert "%20" in link_with_space
    assert "%E3%83%85%E3%82%B9%E3%83%88" in link_with_space or "%E3%83%86%E3%82%B9%E3%83%88" in link_with_space


def test_validate_dashboard_links(tmp_path):
    # テスト用ファイルの準備
    readme_file = tmp_path / "README.md"
    existing_file = tmp_path / "exist.md"
    existing_file.touch()

    # URLエンコードされたリンクを用意
    from urllib.parse import quote
    exist_link = get_rel_link(str(existing_file))
    non_exist_link = get_rel_link(str(tmp_path / "non_exist.md"))

    readme_content = f"""
# Dashboard
- [Existing]({exist_link})
- [Non Existing]({non_exist_link})
"""
    readme_file.write_text(readme_content, encoding="utf-8")

    broken = validate_dashboard_links(str(readme_file))
    assert len(broken) == 1
    assert non_exist_link in broken


def test_record_event_if_changed(tmp_path):
    event_log = tmp_path / "events.jsonl"
    now_jst = "2026-06-15 12:00 JST"

    # 初回記録：ファイルがない状態から
    _record_event_if_changed(str(event_log), "ACTIVE", "HEALTHY", now_jst)
    assert event_log.exists()

    with open(event_log, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["lifecycle"] == "ACTIVE"
    assert data["health"] == "HEALTHY"

    # 同一状態での記録：変化がないので書き込まれないはず
    _record_event_if_changed(str(event_log), "ACTIVE", "HEALTHY", now_jst)
    with open(event_log, "r", encoding="utf-8") as f:
        lines2 = f.readlines()
    assert len(lines2) == 1

    # 状態変化での記録：書き込まれるはず
    _record_event_if_changed(str(event_log), "FINISHING", "HEALTHY", now_jst)
    with open(event_log, "r", encoding="utf-8") as f:
        lines3 = f.readlines()
    assert len(lines3) == 2
    data3 = json.loads(lines3[1])
    assert data3["lifecycle"] == "FINISHING"
    assert "lifecycle: ACTIVE → FINISHING" in data3["change"]


def test_record_topic_event(tmp_path):
    event_log = tmp_path / "events.jsonl"
    now_jst = "2026-06-15 12:00 JST"

    _record_topic_event(str(event_log), now_jst, "incident", "QUOTA_EXHAUSTED", "API quota limit reached")
    assert event_log.exists()

    with open(event_log, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["lifecycle"] == "TOPIC"
    assert data["category"] == "incident"
    assert data["topic"] == "QUOTA_EXHAUSTED"
    assert data["detail"] == "API quota limit reached"


def test_read_recent_events(tmp_path):
    event_log = tmp_path / "events.jsonl"
    
    # 24時間以内のイベントと24時間より前のイベントを作成
    now = datetime.now()
    ts_now = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M JST")
    ts_old = (now - timedelta(hours=26)).strftime("%Y-%m-%d %H:%M JST")

    # 旧イベント
    _record_event_if_changed(str(event_log), "ACTIVE", "HEALTHY", ts_old)
    # 新イベント
    _record_event_if_changed(str(event_log), "STOPPED", "UNHEALTHY", ts_now)

    md = _read_recent_events(str(event_log))
    
    # 直近24時間のイベントのみがタイムラインに含まれる
    assert "⏹️ セッション停止" in md or "自動停止" in md or "異常検出" in md
    # タイムラインのマークダウンにタイムロスなどの記述があること
    assert "介入タイムライン" in md


def test_get_rel_link_invalid_type():
    # 非文字列の入力に対して安全に空文字列を返すことの検証
    assert get_rel_link(None) == ""
    assert get_rel_link(123) == ""
    assert get_rel_link([]) == ""


def test_validate_dashboard_links_invalid_type():
    # 非文字列の入力に対して安全に空リストを返すことの検証
    assert validate_dashboard_links(None) == []
    assert validate_dashboard_links(123) == []
    assert validate_dashboard_links([]) == []


def test_record_event_if_changed_broken_json(tmp_path):
    event_log = tmp_path / "events.jsonl"
    
    # 壊れたJSON（辞書ではない）を事前にログファイルに書き込んでおく
    with open(event_log, "w", encoding="utf-8") as f:
        f.write("[]\n")  # 辞書ではなくリスト
        f.write("123\n") # 辞書ではなく数値
        f.write('"invalid_json_string"\n')
    
    now_jst = "2026-06-15 12:00 JST"
    # クラッシュせずに処理が成功すること
    _record_event_if_changed(str(event_log), "ACTIVE", "HEALTHY", now_jst)
    
    assert event_log.exists()
    with open(event_log, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # 追記が成功していること
    assert len(lines) == 4
    last_event = json.loads(lines[-1])
    assert last_event["lifecycle"] == "ACTIVE"
    assert last_event["health"] == "HEALTHY"


def test_read_recent_events_broken_data(tmp_path):
    event_log = tmp_path / "events.jsonl"
    now = datetime.now()
    ts_now_1 = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M JST")
    ts_now_2 = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M JST")
    
    # timestampがNoneや非文字列、不正なJSON、あるいは辞書ではない行を混在させる
    with open(event_log, "w", encoding="utf-8") as f:
        # 1. 正常な24時間以内の行
        f.write(json.dumps({"timestamp": ts_now_1, "lifecycle": "ACTIVE", "health": "HEALTHY", "change": []}) + "\n")
        # 2. timestampがnullの行
        f.write(json.dumps({"timestamp": None, "lifecycle": "ACTIVE", "health": "HEALTHY", "change": []}) + "\n")
        # 3. timestampが整数(型エラー)の行
        f.write(json.dumps({"timestamp": 123456, "lifecycle": "ACTIVE", "health": "HEALTHY", "change": []}) + "\n")
        # 4. 辞書ではない行
        f.write("[1, 2, 3]\n")
        # 5. 不正なJSON
        f.write("{invalid json\n")
        # 6. 正常な24時間以内の停止イベント行
        f.write(json.dumps({"timestamp": ts_now_2, "lifecycle": "STOPPED", "health": "UNHEALTHY", "change": ["lifecycle: ACTIVE → STOPPED"]}) + "\n")

    # クラッシュせずにタイムラインが生成できること
    md = _read_recent_events(str(event_log))
    assert "介入タイムライン" in md
    assert "⏹️ セッション停止" in md or "停止" in md


def test_record_event_io_error(tmp_path, capsys):
    # 存在しないディレクトリのパスなど、書き込みが失敗するようなパスを指定
    invalid_path = "/non_existent_directory_xyz/events.jsonl" if os.name != "nt" else "Z:\\non_existent_directory_xyz\\events.jsonl"
    
    # クラッシュせずに警告が stderr に出力されること
    _record_event_if_changed(invalid_path, "ACTIVE", "HEALTHY", "2026-06-15 12:00 JST")
    _record_topic_event(invalid_path, "2026-06-15 12:00 JST", "incident", "TEST_ERROR", "Test error detail")
    
    captured = capsys.readouterr()
    assert "Failed to write event" in captured.err
    assert "Failed to write topic event" in captured.err
