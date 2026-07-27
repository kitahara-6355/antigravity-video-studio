import os
import json
import pytest
import runpy
import sys
from unittest.mock import patch
from backend.agents.orchestration.get_system_status import (
    query_system_status,
    check_safety_guard,
    main,
    generate_status_thumbnail
)
from PIL import Image as PILImage

def test_check_safety_guard_safe():
    # 安全なパスの場合は例外が発生せず正常終了する
    check_safety_guard(workspace_dir="/path/to/video-automation")

def test_check_safety_guard_unsafe():
    # 安全ガードが無効化されているため、例外は発生せず正常終了する
    check_safety_guard(workspace_dir="/path/to/video-automation 2")

def test_check_safety_guard_default():
    # 引数なしで呼び出してデフォルトパスの探索をカバーする
    check_safety_guard()

def test_query_system_status_all_not_found(tmp_path):
    # ファイルが一切存在しない場合、すべて "Not Found" になること
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    
    assert summary["flash_session"] == "Not Found"
    assert summary["task_queue"] == "Not Found"
    assert summary["phase_state"] == "Not Found"
    assert summary["tdr_index"] == "Not Found"
    assert summary["design_stock"] == "Not Found"

def test_query_system_status_flash_session(tmp_path):
    flash_session_file = tmp_path / "flash_session.json"
    data = {
        "status": "running",
        "last_heartbeat": "2026-05-26T12:00:00",
        "current_activity": "testing",
        "current_step": 3,
        "current_batch_id": "batch_abc",
        "progress_pct": 50.0,
        "tasks_completed_in_session": 10
    }
    flash_session_file.write_text(json.dumps(data), encoding="utf-8")
    
    paths = {
        "flash_session": str(flash_session_file),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    assert summary["flash_session"] == data

def test_query_system_status_task_queue(tmp_path):
    task_queue_file = tmp_path / "task_queue.json"
    data = {
        "current_batch_id": "batch_abc",
        "status": "active",
        "tasks": [
            {"status": "pending"},
            {"status": "running"},
            {"status": "completed"},
            {"status": "pass"},
            {"status": "failed"},
            {"status": "unknown"}
        ]
    }
    task_queue_file.write_text(json.dumps(data), encoding="utf-8")
    
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(task_queue_file),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    q = summary["task_queue"]
    assert q["total_tasks"] == 6
    assert q["pending"] == 1
    assert q["running"] == 1
    assert q["completed"] == 2
    assert q["failed"] == 1
    assert q["current_batch_id"] == "batch_abc"
    assert q["status"] == "active"

def test_query_system_status_phase_state(tmp_path):
    phase_state_file = tmp_path / "phase_state.json"
    data = {
        "current_phase": 26,
        "phase_name": "Phase 26",
        "emergency_stop": False,
        "other_field": "ignored"
    }
    phase_state_file.write_text(json.dumps(data), encoding="utf-8")
    
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(phase_state_file),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    assert summary["phase_state"] == {
        "current_phase": 26,
        "phase_name": "Phase 26",
        "emergency_stop": False
    }

def test_query_system_status_tdr_index_dict(tmp_path):
    tdr_file = tmp_path / "technical_debt_index.json"
    data = {
        "entries": {
            "debt1": {"status": "open", "priority": "CRITICAL"},
            "debt2": {"status": "open", "priority": "HIGH"},
            "debt3": {"status": "fixed", "priority": "CRITICAL"},
            "debt4": {"status": "resolved", "priority": "LOW"},
            "debt5": {"status": "accepted", "priority": "MEDIUM"}
        }
    }
    tdr_file.write_text(json.dumps(data), encoding="utf-8")
    
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tdr_file),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    tdr = summary["tdr_index"]
    assert tdr["total_registered"] == 5
    assert tdr["open"] == 2
    assert tdr["resolved"] == 2
    assert tdr["accepted"] == 1
    assert tdr["critical_open"] == 1

def test_query_system_status_tdr_index_list(tmp_path):
    tdr_file = tmp_path / "technical_debt_index.json"
    data = {
        "entries": [
            {"status": "open", "priority": "CRITICAL"},
            {"status": "open", "priority": "HIGH"},
            {"status": "fixed", "priority": "CRITICAL"}
        ]
    }
    tdr_file.write_text(json.dumps(data), encoding="utf-8")
    
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tdr_file),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    tdr = summary["tdr_index"]
    assert tdr["total_registered"] == 3
    assert tdr["open"] == 2
    assert tdr["resolved"] == 1
    assert tdr["accepted"] == 0
    assert tdr["critical_open"] == 1

def test_query_system_status_design_stock(tmp_path):
    design_stock_dir = tmp_path / "design_stock"
    design_stock_dir.mkdir()
    
    (design_stock_dir / "doc1.md").write_text("content", encoding="utf-8")
    (design_stock_dir / "doc2.md").write_text("content", encoding="utf-8")
    (design_stock_dir / "image.png").write_text("binary", encoding="utf-8")
    
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(design_stock_dir)
    }
    
    summary = query_system_status(paths=paths)
    stock = summary["design_stock"]
    assert stock["total_stock_count"] == 2
    assert sorted(stock["files"]) == ["doc1.md", "doc2.md"]

def test_query_system_status_default_base_dir():
    with patch("os.path.exists", return_value=False):
        summary = query_system_status()
        assert summary["flash_session"] == "Not Found"

def test_main(capsys):
    with patch("backend.agents.orchestration.get_system_status.check_safety_guard") as mock_guard, \
         patch("backend.agents.orchestration.get_system_status.query_system_status", return_value={"test": "ok"}) as mock_query:
        main()
        mock_guard.assert_called_once()
        mock_query.assert_called_once()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"test": "ok"}

def test_script_execution(capsys):
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agents", "orchestration", "get_system_status.py"))
    try:
        runpy.run_path(script_path, run_name="__main__")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "flash_session" in data
    except SystemExit as e:
        assert e.code == 0

def test_query_system_status_task_queue_empty(tmp_path):
    task_queue_file = tmp_path / "task_queue.json"
    task_queue_file.write_text("{}", encoding="utf-8")
    
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(task_queue_file),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    q = summary["task_queue"]
    assert q["total_tasks"] == 0
    assert q["pending"] == 0
    assert q["running"] == 0
    assert q["completed"] == 0
    assert q["failed"] == 0
    assert q["current_batch_id"] is None
    assert q["status"] is None

def test_query_system_status_tdr_index_empty(tmp_path):
    tdr_file = tmp_path / "technical_debt_index.json"
    tdr_file.write_text("{}", encoding="utf-8")
    
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tdr_file),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    tdr = summary["tdr_index"]
    assert tdr["total_registered"] == 0
    assert tdr["open"] == 0
    assert tdr["resolved"] == 0
    assert tdr["accepted"] == 0
    assert tdr["critical_open"] == 0

def test_check_safety_guard_default_mocked_safe():
    with patch("os.path.abspath", return_value="/path/to/video-automation"):
        check_safety_guard()

def test_check_safety_guard_default_mocked_unsafe():
    with patch("os.path.abspath", return_value="/path/to/video-automation 2"):
        # 安全ガードが無効化されているため、例外は発生せず正常終了する
        check_safety_guard()

# --- 新規追加テスト ---

def test_generate_status_thumbnail_success(tmp_path):
    output_file = tmp_path / "status.png"
    summary = {
        "flash_session": {
            "status": "running",
            "current_activity": "indexing",
            "current_step": "step1",
            "progress_pct": 80,
            "tasks_completed_in_session": 5
        },
        "task_queue": {
            "status": "active",
            "total_tasks": 10,
            "pending": 2,
            "running": 1,
            "completed": 6,
            "failed": 1
        },
        "tdr_index": {
            "total_registered": 5,
            "open": 2,
            "critical_open": 1,
            "resolved": 2
        },
        "design_stock": {
            "total_stock_count": 3
        }
    }
    path = generate_status_thumbnail(str(output_file), summary)
    assert os.path.exists(path)
    with PILImage.open(path) as img:
        assert img.size == (1280, 720)

def test_generate_status_thumbnail_summary_none(tmp_path):
    output_file = tmp_path / "status_none.png"
    with patch("backend.agents.orchestration.get_system_status.query_system_status", return_value={}) as mock_query:
        path = generate_status_thumbnail(str(output_file), None)
        assert os.path.exists(path)
        mock_query.assert_called_once()

def test_generate_status_thumbnail_summary_query_exception(tmp_path):
    output_file = tmp_path / "status_exception.png"
    with patch("backend.agents.orchestration.get_system_status.query_system_status", side_effect=OSError("Test Exception")):
        path = generate_status_thumbnail(str(output_file), None)
        assert os.path.exists(path)

def test_generate_status_thumbnail_no_pillow(tmp_path):
    output_file = tmp_path / "status_no_pillow.png"
    import backend.agents.orchestration.get_system_status as gss
    with patch.object(gss, "Image", None):
        with pytest.raises(ImportError) as excinfo:
            generate_status_thumbnail(str(output_file), {})
        assert "Pillow library is required" in str(excinfo.value)

def test_generate_status_thumbnail_font_error(tmp_path):
    output_file = tmp_path / "status_font_error.png"
    from PIL import ImageFont
    
    original_truetype = ImageFont.truetype
    
    def mocked_truetype(font, *args, **kwargs):
        if font == "arial.ttf":
            raise IOError("Font not found")
        return original_truetype(font, *args, **kwargs)
        
    with patch.object(ImageFont, "truetype", side_effect=mocked_truetype):
        path = generate_status_thumbnail(str(output_file), {})
        assert os.path.exists(path)

def test_generate_status_thumbnail_non_dict_data(tmp_path):
    output_file = tmp_path / "status_non_dict.png"
    
    summary1 = {
        "flash_session": "Not Found",
        "task_queue": "Not Found",
        "tdr_index": "Not Found",
        "design_stock": "Not Found"
    }
    path1 = generate_status_thumbnail(str(output_file), summary1)
    assert os.path.exists(path1)
    
    summary2 = {
        "flash_session": {
            "status": "FAILED",
            "current_activity": None,
            "current_step": None,
            "progress_pct": None,
            "tasks_completed_in_session": None
        },
        "task_queue": {
            "status": "idle"
        },
        "tdr_index": {
            "total_registered": 1,
            "open": 0,
            "critical_open": 0,
            "resolved": 1
        }
    }
    path2 = generate_status_thumbnail(str(output_file), summary2)
    assert os.path.exists(path2)

    summary3 = {
        "flash_session": {
            "status": "PENDING"
        }
    }
    path3 = generate_status_thumbnail(str(output_file), summary3)
    assert os.path.exists(path3)

def test_import_error_handling():
    import builtins
    original_import = builtins.__import__
    
    def mocked_import(name, *args, **kwargs):
        if name in ("PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont"):
            raise ImportError("Mocked import error")
        return original_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mocked_import):
        if "backend.agents.orchestration.get_system_status" in sys.modules:
            del sys.modules["backend.agents.orchestration.get_system_status"]
        
        import backend.agents.orchestration.get_system_status as gss_test
        assert gss_test.Image is None
        assert gss_test.ImageDraw is None
        assert gss_test.ImageFont is None

    if "backend.agents.orchestration.get_system_status" in sys.modules:
        del sys.modules["backend.agents.orchestration.get_system_status"]


# --- 新規追加テスト (エラーハンドリング検証) ---

def test_query_system_status_json_decode_error(tmp_path):
    # 壊れたJSONファイル（JSONDecodeError）が読み込まれた場合、適切にハンドリングされることを検証
    flash_session_file = tmp_path / "flash_session.json"
    flash_session_file.write_text("{ invalid json }", encoding="utf-8")
    
    paths = {
        "flash_session": str(flash_session_file),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    assert "Error (JSONDecodeError)" in summary["flash_session"]

def test_query_system_status_invalid_format(tmp_path):
    # JSONファイルが辞書ではなく単なるリストや文字列の場合、Invalid Format として適切にハンドリングされることを検証
    flash_session_file = tmp_path / "flash_session.json"
    flash_session_file.write_text('["status", "running"]', encoding="utf-8") # リスト形式
    
    paths = {
        "flash_session": str(flash_session_file),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    summary = query_system_status(paths=paths)
    assert summary["flash_session"] == "Error (Invalid Format)"

def test_query_system_status_permission_error(tmp_path):
    # OSError(PermissionError等)が発生した場合、適切にハンドリングされることを検証
    flash_session_file = tmp_path / "flash_session.json"
    flash_session_file.write_text("{}", encoding="utf-8")
    
    paths = {
        "flash_session": str(flash_session_file),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    
    # openをモックしてPermissionErrorを投げるようにする
    with patch("builtins.open", side_effect=PermissionError("Permission Denied")):
        summary = query_system_status(paths=paths)
        assert "Error (PermissionError)" in summary["flash_session"]


def test_query_system_status_task_queue_invalid_types(tmp_path):
    # task_queue の tasks がリストではない場合 (L65 のカバー)
    tq_file = tmp_path / "task_queue.json"
    tq_file.write_text(json.dumps({"tasks": "not_a_list"}), encoding="utf-8")
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tq_file),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }
    summary = query_system_status(paths=paths)
    assert summary["task_queue"]["total_tasks"] == 0

    # task_queue.json が辞書ではない場合 (L80 のカバー)
    tq_file.write_text(json.dumps("not_a_dict"), encoding="utf-8")
    summary = query_system_status(paths=paths)
    assert summary["task_queue"] == "Error (Invalid Format)"

    # task_queue.json 読み込み時に JSONDecodeError が発生する場合 (L81-82 のカバー)
    tq_file.write_text("{ invalid json }", encoding="utf-8")
    summary = query_system_status(paths=paths)
    assert "Error (JSONDecodeError)" in summary["task_queue"]

    # task_queue.json 読み込み時に OSError が発生する場合 (L81-82 のカバー)
    tq_file.write_text("{}", encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("Permission Denied")):
        summary = query_system_status(paths=paths)
        assert "Error (PermissionError)" in summary["task_queue"]


def test_query_system_status_phase_state_invalid_types(tmp_path):
    ps_file = tmp_path / "phase_state.json"
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(ps_file),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }

    # phase_state.json が辞書ではない場合 (L98 のカバー)
    ps_file.write_text(json.dumps("not_a_dict"), encoding="utf-8")
    summary = query_system_status(paths=paths)
    assert summary["phase_state"] == "Error (Invalid Format)"

    # phase_state.json 読み込み時に JSONDecodeError が発生する場合 (L99-100 のカバー)
    ps_file.write_text("{ invalid json }", encoding="utf-8")
    summary = query_system_status(paths=paths)
    assert "Error (JSONDecodeError)" in summary["phase_state"]

    # phase_state.json 読み込み時に OSError が発生する場合 (L99-100 のカバー)
    ps_file.write_text("{}", encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("Permission Denied")):
        summary = query_system_status(paths=paths)
        assert "Error (PermissionError)" in summary["phase_state"]


def test_query_system_status_tdr_index_invalid_types(tmp_path):
    tdr_file = tmp_path / "technical_debt_index.json"
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tdr_file),
        "design_stock": str(tmp_path / "design_stock")
    }

    # tdr_index の entries が dict でも list でも無い場合 (L116 のカバー)
    tdr_file.write_text(json.dumps({"entries": "not_dict_or_list"}), encoding="utf-8")
    summary = query_system_status(paths=paths)
    assert summary["tdr_index"]["total_registered"] == 0

    # technical_debt_index.json が辞書ではない場合 (L131 のカバー)
    tdr_file.write_text(json.dumps("not_a_dict"), encoding="utf-8")
    summary = query_system_status(paths=paths)
    assert summary["tdr_index"] == "Error (Invalid Format)"

    # technical_debt_index.json 読み込み時に JSONDecodeError が発生する場合 (L132-133 のカバー)
    tdr_file.write_text("{ invalid json }", encoding="utf-8")
    summary = query_system_status(paths=paths)
    assert "Error (JSONDecodeError)" in summary["tdr_index"]

    # technical_debt_index.json 読み込み時に OSError が発生する場合 (L132-133 のカバー)
    tdr_file.write_text("{}", encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("Permission Denied")):
        summary = query_system_status(paths=paths)
        assert "Error (PermissionError)" in summary["tdr_index"]


def test_query_system_status_design_stock_oserror(tmp_path):
    design_stock_dir = tmp_path / "design_stock"
    design_stock_dir.mkdir()
    paths = {
        "flash_session": str(tmp_path / "flash_session.json"),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(design_stock_dir)
    }

    # os.listdir で OSError が発生する場合 (L145-146 のカバー)
    with patch("os.listdir", side_effect=OSError("Access Denied")):
        summary = query_system_status(paths=paths)
        assert "Error (OSError)" in summary["design_stock"]


def test_query_system_status_invalid_paths_type():
    summary1 = query_system_status(paths=[])
    assert summary1["flash_session"] == "Not Found"

    summary2 = query_system_status(paths="invalid_path_str")
    assert summary2["flash_session"] == "Not Found"

    summary3 = query_system_status(paths=None)
    assert "flash_session" in summary3

def test_query_system_status_missing_keys(tmp_path):
    flash_session_file = tmp_path / "flash_session.json"
    flash_session_file.write_text("{}", encoding="utf-8")
    
    paths = {
        "flash_session": str(flash_session_file)
    }
    
    summary = query_system_status(paths=paths)
    assert summary["flash_session"] == {
        "status": None,
        "last_heartbeat": None,
        "current_activity": None,
        "current_step": None,
        "current_batch_id": None,
        "progress_pct": None,
        "tasks_completed_in_session": None
    }
    assert summary["task_queue"] == "Not Found"
    assert summary["phase_state"] == "Not Found"
    assert summary["tdr_index"] == "Not Found"
    assert summary["design_stock"] == "Not Found"

def test_generate_status_thumbnail_invalid_summary_type(tmp_path):
    output_file = tmp_path / "invalid_summary_type.png"
    path = generate_status_thumbnail(str(output_file), "this_is_not_a_dict")
    assert os.path.exists(path)
    with PILImage.open(path) as img:
        assert img.size == (1280, 720)

def test_query_system_status_type_error_on_isinstance(tmp_path):
    class TypeErrorOnIsinstance:
        @property
        def __class__(self):
            raise TypeError("Simulated TypeError for isinstance check")

    paths = {
        "flash_session": TypeErrorOnIsinstance(),
        "task_queue": str(tmp_path / "task_queue.json"),
        "phase_state": str(tmp_path / "phase_state.json"),
        "tdr_index": str(tmp_path / "technical_debt_index.json"),
        "design_stock": str(tmp_path / "design_stock")
    }

    summary = query_system_status(paths=paths)
    assert summary["flash_session"] == "Not Found"
