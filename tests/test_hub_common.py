import pytest
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
from backend.agents.orchestration.hub_common import (
    _now_iso,
    _safe_parse_iso,
    _get_flash_profile,
    _DEFAULT_FLASH_PROFILES,
    _read_json,
    _write_json,
    _append_jsonl,
    _rotate_jsonl_if_needed,
    _read_jsonl,
)

def test_now_iso():
    """_now_iso が正常に ISO 8601 形式の UTC 時刻を返すこと"""
    val = _now_iso()
    assert isinstance(val, str)
    parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
    assert parsed.tzinfo == timezone.utc

def test_safe_parse_iso_valid():
    """_safe_parse_iso が有効な ISO 8601 文字列を正しくパースすること"""
    dt_str = "2026-06-27T04:27:00Z"
    parsed = _safe_parse_iso(dt_str)
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 6
    assert parsed.day == 27
    assert parsed.hour == 4
    assert parsed.minute == 27
    assert parsed.tzinfo == timezone.utc

    dt_str_offset = "2026-06-27T13:27:00+09:00"
    parsed_offset = _safe_parse_iso(dt_str_offset)
    assert parsed_offset is not None
    assert parsed_offset.hour == 13
    assert parsed_offset.tzinfo is not None

def test_safe_parse_iso_invalid():
    """_safe_parse_iso が無効な値や None を受け取ったときに None を返すこと"""
    assert _safe_parse_iso(None) is None
    assert _safe_parse_iso("invalid-date-string") is None
    assert _safe_parse_iso(12345) is None  # type: ignore

def test_get_flash_profile_fallback():
    """user_schedule.json の読み込みに失敗した場合にデフォルトプロファイルにフォールバックすること"""
    with patch("builtins.open", side_effect=OSError("File not found")):
        profile = _get_flash_profile()
        assert profile is not None
        assert "mode" in profile
        assert profile["batch_size"] == _DEFAULT_FLASH_PROFILES[profile["mode"]]["batch_size"]

@pytest.mark.parametrize(
    "target_time_utc, expected_mode",
    [
        ("2026-06-22T03:00:00Z", "standard"),
        ("2026-06-22T14:00:00Z", "night"),
        ("2026-06-22T21:00:00Z", "night"),
        ("2026-06-22T22:00:00Z", "standard"),
        ("2026-06-27T03:00:00Z", "weekend"),
        ("2026-06-27T13:30:00Z", "weekend"),
        ("2026-06-27T14:30:00Z", "night"),
    ]
)
def test_get_flash_profile_modes(target_time_utc, expected_mode):
    """曜日と時刻に基づいて正しい動作モードが選択されること"""
    dt_mock = datetime.fromisoformat(target_time_utc.replace("Z", "+00:00"))
    
    with patch("backend.agents.orchestration.hub_common.datetime") as mock_datetime, \
         patch("builtins.open", side_effect=OSError):
        mock_datetime.now.return_value = dt_mock
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        profile = _get_flash_profile()
        assert profile["mode"] == expected_mode

def test_get_flash_profile_custom_config():
    """user_schedule.json が正常に読み込めた場合にカスタムプロファイルが適用されること"""
    custom_schedule = {
        "flash_profiles": {
            "standard": {"batch_size": 3, "mode": "standard"},
            "weekend": {"batch_size": 4, "mode": "weekend"},
            "night": {"batch_size": 5, "mode": "night"},
        },
        "mode_schedule": {
            "night_start": "21:00",
            "night_end": "08:00"
        }
    }
    dt_mock = datetime.fromisoformat("2026-06-22T12:30:00+00:00")
    
    m_open = mock_open(read_data=json.dumps(custom_schedule))
    with patch("backend.agents.orchestration.hub_common.datetime") as mock_datetime, \
         patch("builtins.open", m_open):
        mock_datetime.now.return_value = dt_mock
        profile = _get_flash_profile()
        assert profile["mode"] == "night"
        assert profile["batch_size"] == 5

def test_get_flash_profile_night_start_less_than_end():
    """night_start <= night_end の場合の夜間判定ロジック（分岐）が正しくカバーされること"""
    custom_schedule = {
        "flash_profiles": {
            "standard": {"batch_size": 3, "mode": "standard"},
            "night": {"batch_size": 5, "mode": "night"},
        },
        "mode_schedule": {
            "night_start": "01:00",
            "night_end": "05:00"
        }
    }
    
    # 正常系1: 夜間時間帯内 JST 03:00 (UTC 18:00 前日)
    dt_mock_in = datetime.fromisoformat("2026-06-21T18:00:00+00:00")
    m_open = mock_open(read_data=json.dumps(custom_schedule))
    with patch("backend.agents.orchestration.hub_common.datetime") as mock_datetime, \
         patch("builtins.open", m_open):
        mock_datetime.now.return_value = dt_mock_in
        profile = _get_flash_profile()
        assert profile["mode"] == "night"

    # 正常系2: 夜間時間帯外 JST 06:00 (UTC 21:00 前日) -> 平日なので standard
    dt_mock_out = datetime.fromisoformat("2026-06-21T21:00:00+00:00")
    m_open = mock_open(read_data=json.dumps(custom_schedule))
    with patch("backend.agents.orchestration.hub_common.datetime") as mock_datetime, \
         patch("builtins.open", m_open):
        mock_datetime.now.return_value = dt_mock_out
        profile = _get_flash_profile()
        assert profile["mode"] == "standard"

# --- JSON / JSONL I/O テスト ---

def test_read_json_nonexistent():
    """存在しないファイルを読み込んだ場合、空の辞書を返すこと"""
    path = Path("nonexistent_file_xyz.json")
    assert _read_json(path) == {}

def test_read_json_valid(tmp_path):
    """正常な JSON ファイルを正しく読み込めること"""
    path = tmp_path / "valid.json"
    data = {"key": "value", "number": 42}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert _read_json(path) == data

def test_read_json_invalid(tmp_path):
    """破損した JSON ファイルを読み込んだ場合、エラーログを出力して空辞書を返すこと"""
    path = tmp_path / "invalid.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write("{invalid json")
    
    with patch("backend.agents.orchestration.hub_common.logger.error") as mock_log:
        result = _read_json(path)
        assert result == {}
        mock_log.assert_called_once()
        assert "Failed to read json" in mock_log.call_args[0][0]

def test_write_json_success(tmp_path):
    """正常に JSON ファイルをアトミックに書き込めること"""
    path = tmp_path / "output.json"
    data = {"hello": "world"}
    _write_json(path, data)
    
    assert path.exists()
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data

def test_write_json_failure_cleanup(tmp_path):
    """書き込み中に OSError が発生した場合、一時ファイルが削除され例外が送出されること"""
    path = tmp_path / "output_fail.json"
    data = {"hello": "world"}
    
    with patch("pathlib.Path.replace", side_effect=OSError("Disk full")), \
         patch("backend.agents.orchestration.hub_common.logger.error") as mock_log:
        with pytest.raises(OSError):
            _write_json(path, data)
        
        mock_log.assert_called_once()
        assert "Failed to write json" in mock_log.call_args[0][0]
        assert not path.exists()

def test_write_json_failure_unlink_error(tmp_path):
    """書き込みエラー発生時のクリーンアップで、一時ファイルの削除自体が失敗した場合に例外が伝播すること"""
    path = tmp_path / "output_fail_unlink.json"
    data = {"hello": "world"}
    
    with patch("pathlib.Path.replace", side_effect=OSError("Disk full")), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", side_effect=OSError("Unlink failed")), \
         patch("backend.agents.orchestration.hub_common.logger.error") as mock_log:
         
        with pytest.raises(OSError) as exc:
            _write_json(path, data)
        assert "Disk full" in str(exc.value)

def test_read_jsonl_nonexistent():
    """存在しない JSONL ファイルを読み込んだ場合、空の配列を返すこと"""
    path = Path("nonexistent_file_xyz.jsonl")
    assert _read_jsonl(path) == []

def test_read_jsonl_mixed(tmp_path):
    """一部破損した行を含む JSONL ファイルから正常な行のみを読み込めること"""
    path = tmp_path / "mixed.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"index": 1}\n')
        f.write('{invalid json line}\n')
        f.write('{"index": 2}\n')
        f.write('\n')
    
    records = _read_jsonl(path)
    assert len(records) == 2
    assert records[0] == {"index": 1}
    assert records[1] == {"index": 2}

def test_append_jsonl_and_rotation(tmp_path):
    """JSONL ファイルへの追記と自動ローテーションが正しく機能すること"""
    path = tmp_path / "stream.jsonl"
    
    _append_jsonl(path, {"val": 1})
    _append_jsonl(path, {"val": 2})
    
    records = _read_jsonl(path)
    assert records == [{"val": 1}, {"val": 2}]

    _rotate_jsonl_if_needed(path, max_lines=1)
    
    remaining = _read_jsonl(path)
    assert remaining == [{"val": 2}]
    
    archives = list(tmp_path.glob("stream.archive.*.jsonl"))
    assert len(archives) == 1
    archive_records = _read_jsonl(archives[0])
    assert archive_records == [{"val": 1}]

def test_append_jsonl_creates_parent_dir(tmp_path):
    """_append_jsonl が存在しない親ディレクトリを自動で作成すること"""
    parent_dir = tmp_path / "new_subdir"
    path = parent_dir / "stream.jsonl"
    
    assert not parent_dir.exists()
    _append_jsonl(path, {"val": 100})
    
    assert parent_dir.exists()
    assert path.exists()
    assert _read_jsonl(path) == [{"val": 100}]

def test_rotate_jsonl_failure(tmp_path):
    """ローテーション中に例外が発生した場合、警告ログを出力しクラッシュしないこと"""
    path = tmp_path / "fail_rotation.jsonl"
    _append_jsonl(path, {"val": 1})
    
    with patch("backend.agents.orchestration.hub_common._read_jsonl", side_effect=OSError("Read error")), \
         patch("backend.agents.orchestration.hub_common.logger.warning") as mock_log:
        
        _rotate_jsonl_if_needed(path, max_lines=0)
        mock_log.assert_called_once()
        assert "JSONL rotation failed" in mock_log.call_args[0][0]


# --- エッジケーステスト ---

def test_safe_parse_iso_edge_cases():
    """_safe_parse_iso に対するエッジケース（巨大入力、不正型、空文字列）の検証"""
    # 巨大入力
    huge_str = "2026-06-27T04:27:00Z" + "A" * 100000
    assert _safe_parse_iso(huge_str) is None

    # 不正型
    assert _safe_parse_iso({"date": "2026-06-27"}) is None  # type: ignore
    assert _safe_parse_iso(["2026-06-27"]) is None  # type: ignore
    assert _safe_parse_iso(12345) is None  # type: ignore

    # 空文字列 / スペース
    assert _safe_parse_iso("") is None
    assert _safe_parse_iso("   ") is None
    assert _safe_parse_iso("\n") is None


def test_get_flash_profile_invalid_schedule_types():
    """_get_flash_profile に対する不正な schedule 設定でのエッジケース検証"""
    # 1. flash_profiles が空、または不正な値の場合
    custom_schedule_invalid_profiles = {
        "flash_profiles": {
            "standard": None,
            "weekend": {},
        }
    }
    # 平日 JST 12:00 (UTC 03:00) -> standard -> プロファイルは None
    dt_mock = datetime.fromisoformat("2026-06-22T03:00:00+00:00")
    m_open = mock_open(read_data=json.dumps(custom_schedule_invalid_profiles))
    with patch("backend.agents.orchestration.hub_common.datetime") as mock_datetime, \
         patch("builtins.open", m_open):
        mock_datetime.now.return_value = dt_mock
        # profile["mode"] = mode で TypeError: 'NoneType' object does not support item assignment が発生するはず
        with pytest.raises(TypeError):
            _get_flash_profile()

    # 2. mode_schedule で night_start や night_end が None の場合
    custom_schedule_invalid_schedule = {
        "mode_schedule": {
            "night_start": None,
            "night_end": None
        }
    }
    m_open = mock_open(read_data=json.dumps(custom_schedule_invalid_schedule))
    with patch("backend.agents.orchestration.hub_common.datetime") as mock_datetime, \
         patch("builtins.open", m_open):
        mock_datetime.now.return_value = dt_mock
        # night_start > night_end -> None > None (TypeError)
        with pytest.raises(TypeError):
            _get_flash_profile()


def test_read_json_edge_cases(tmp_path):
    """_read_json に対するエッジケース（巨大入力、空ファイル、ディレクトリ指定、不正型）の検証"""
    # 1. 空ファイル (0バイト)
    empty_file = tmp_path / "empty.json"
    empty_file.touch()
    assert _read_json(empty_file) == {}

    # 2. ディレクトリを指定した場合
    dir_path = tmp_path / "sub_directory"
    dir_path.mkdir()
    # ディレクトリなので exists() は True だが読み込みは失敗し、ログを出力して空辞書を返す
    with patch("backend.agents.orchestration.hub_common.logger.error") as mock_log:
        assert _read_json(dir_path) == {}
        mock_log.assert_called_once()

    # 3. 巨大入力 (巨大なネスト)
    huge_file = tmp_path / "huge.json"
    nested_data = {}
    current = nested_data
    for i in range(500):
        current["k"] = {}
        current = current["k"]
    with open(huge_file, "w", encoding="utf-8") as f:
        json.dump(nested_data, f)
    
    assert _read_json(huge_file) == nested_data

    # 4. 不正型 (Path以外の型)
    # path.exists() で AttributeError などの例外が起きることを確認
    with pytest.raises((AttributeError, TypeError)):
        _read_json(12345)  # type: ignore


def test_write_json_edge_cases(tmp_path):
    """_write_json に対するエッジケース（非シリアライズオブジェクト、巨大入力、不正型）の検証"""
    path = tmp_path / "edge_output.json"

    # 1. 非シリアライズオブジェクト (set など) -> json.dump が TypeError を発生させ、伝播する
    with pytest.raises(TypeError):
        _write_json(path, {"invalid_val": {1, 2, 3}})  # set は json シリアライズ不可

    # 2. 巨大入力 (大量のキー)
    huge_data = {f"key_{i}": "value" * 100 for i in range(2000)}
    _write_json(path, huge_data)
    assert path.exists()
    assert _read_json(path) == huge_data

    # 3. 不正型 (辞書以外のデータ)
    # json.dump(data, f) は辞書以外 (リストやプリミティブ値) もシリアライズ可能なので、正常終了する
    list_path = tmp_path / "list_output.json"
    _write_json(list_path, [1, 2, 3])  # type: ignore
    assert list_path.exists()
    with open(list_path, "r", encoding="utf-8") as f:
        assert json.load(f) == [1, 2, 3]


def test_append_jsonl_edge_cases(tmp_path):
    """_append_jsonl に対するエッジケース（非シリアライズオブジェクト、巨大入力）の検証"""
    path = tmp_path / "edge_stream.jsonl"

    # 1. 非シリアライズオブジェクト
    with pytest.raises(TypeError):
        _append_jsonl(path, {"invalid_val": {1, 2, 3}})  # type: ignore

    # 2. 巨大入力
    huge_record = {"data": "A" * 50000}
    _append_jsonl(path, huge_record)
    assert _read_jsonl(path) == [huge_record]


def test_rotate_jsonl_if_needed_edge_cases(tmp_path):
    """_rotate_jsonl_if_needed に対するエッジケース（境界値、不正型、空ファイル）の検証"""
    path = tmp_path / "rotate_edge.jsonl"

    # 1. 空ファイル
    _rotate_jsonl_if_needed(path, max_lines=10)  # 例外が起きず正常にリターンすること
    assert not path.exists()

    # 2. 境界値 (max_lines = 0)
    _append_jsonl(path, {"val": 1})
    _append_jsonl(path, {"val": 2})
    # Pythonのスライスの仕様上、max_lines=0 のときは records[:-0] が空リストになり、
    # records[-0:] がリスト全体になるため、アーカイブは空で、元のファイルに全件残る挙動となる
    _rotate_jsonl_if_needed(path, max_lines=0)
    assert _read_jsonl(path) == [{"val": 1}, {"val": 2}]
    archives = list(tmp_path.glob("rotate_edge.archive.*.jsonl"))
    # アーカイブファイル自体は作成され、中身は空になる
    assert len(archives) == 1
    assert _read_jsonl(archives[0]) == []

    # 3. 境界値 (max_lines = 負の数)
    path_neg = tmp_path / "rotate_neg.jsonl"
    _append_jsonl(path_neg, {"val": 1})
    _append_jsonl(path_neg, {"val": 2})
    # max_lines = -1 の場合、records[:-(-1)] -> records[:1] (最初の1件がアーカイブ), 
    # records[-(-1):] -> records[1:] (最後の1件が残存)
    _rotate_jsonl_if_needed(path_neg, max_lines=-1)
    assert _read_jsonl(path_neg) == [{"val": 2}]
    archives_neg = list(tmp_path.glob("rotate_neg.archive.*.jsonl"))
    assert len(archives_neg) == 1
    assert _read_jsonl(archives_neg[0]) == [{"val": 1}]

    # 4. 不正型 (max_lines が文字列など)
    # 内部で TypeError などが発生するが、try-except でキャッチされ警告ログが出る
    with patch("backend.agents.orchestration.hub_common.logger.warning") as mock_warn:
        _rotate_jsonl_if_needed(path_neg, max_lines="invalid")  # type: ignore
        mock_warn.assert_called_once()
        assert "JSONL rotation failed" in mock_warn.call_args[0][0]


def test_read_jsonl_edge_cases(tmp_path):
    """_read_jsonl に対するエッジケース（巨大入力、ディレクトリ指定、不正型）の検証"""
    # 1. 巨大入力 (大量の行)
    path = tmp_path / "huge_lines.jsonl"
    records = [{"num": i} for i in range(2000)]
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    
    assert _read_jsonl(path) == records

    # 2. ディレクトリを指定した場合
    dir_path = tmp_path / "sub_dir_jsonl"
    dir_path.mkdir()
    # _read_jsonl は path.exists() は True になるが、open(path) で OSError が起きる。
    # この関数は例外をキャッチしていないため、呼び出し元に OSError が伝播することを確認する。
    with pytest.raises(OSError):
        _read_jsonl(dir_path)

    # 3. 不正型
    with pytest.raises((AttributeError, TypeError)):
        _read_jsonl(12345)  # type: ignore

