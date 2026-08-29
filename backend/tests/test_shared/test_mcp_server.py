import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest
from fastapi.testclient import TestClient

# Ensure backend directory is in python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import backend.mcp_server as mcp_server


def test_load_json_success(tmp_path):
    test_file = tmp_path / "test.json"
    data = {"key": "value"}
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    res = mcp_server._load_json_safely(test_file)
    assert res == data


def test_load_json_not_found():
    res = mcp_server._load_json_safely(Path("non_existent_file.json"))
    assert res == {}


def test_load_json_invalid(tmp_path):
    test_file = tmp_path / "test.json"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("invalid json")

    res = mcp_server._load_json_safely(test_file)
    assert res == {}


def test_get_pipeline_status_no_file():
    with patch("backend.mcp_server._load_json_safely", return_value={}):
        status = mcp_server.get_pipeline_status()
        assert status["status"] == "idle"
        assert status["message"] == "パイプラインは待機中です"


def test_get_pipeline_status_with_file():
    state_data = {
        "status": "processing",
        "current_stage": "rendering",
        "progress": 50,
        "video_file": "output.mp4",
        "started_at": "2026-05-22T08:00:00",
        "stages_completed": 2,
    }
    with patch("backend.mcp_server._load_json_safely", return_value=state_data):
        status = mcp_server.get_pipeline_status()
        assert status["status"] == "processing"
        assert status["current_stage"] == "rendering"
        assert status["progress"] == 50
        assert status["video_file"] == "output.mp4"
        assert status["started_at"] == "2026-05-22T08:00:00"
        assert status["stages_completed"] == 2


def test_get_quality_score_no_file():
    with patch.object(Path, "exists", return_value=False):
        score = mcp_server.get_quality_score()
        assert score["score"] is None
        assert "score" in score


def test_get_quality_score_success():
    stages_data = [
        {"name": "stage1", "completed": True},
        {"name": "stage2", "completed": True},
        {"name": "stage3", "completed": False},
    ]
    log_entry = {
        "approved_at": "2026-05-22T09:00:00",
        "stages": stages_data,
    }
    read_data = json.dumps(log_entry) + "\n"
    
    m = mock_open(read_data=read_data)
    m.return_value.readlines.return_value = [read_data]
    
    with patch("builtins.open", m):
        with patch.object(Path, "exists", return_value=True):
            score = mcp_server.get_quality_score()
            assert score["score"] == 67  # round(2/3 * 100)
            assert score["stages_total"] == 3
            assert score["stages_completed"] == 2
            assert score["approved_at"] == "2026-05-22T09:00:00"


def test_get_quality_score_empty_file():
    m = mock_open(read_data="")
    m.return_value.readlines.return_value = []
    with patch("builtins.open", m):
        with patch.object(Path, "exists", return_value=True):
            score = mcp_server.get_quality_score()
            assert score["score"] is None
            assert score["message"] == "解析エラー"


def test_get_quality_score_invalid_json():
    m = mock_open(read_data="invalid json\n")
    m.return_value.readlines.return_value = ["invalid json\n"]
    with patch("builtins.open", m):
        with patch.object(Path, "exists", return_value=True):
            score = mcp_server.get_quality_score()
            assert score["score"] is None
            assert score["message"] == "解析エラー"


def test_get_evolution_log():
    evo_data = {
        "entries": ["entry1", "entry2"],
        "philosophies": ["phil1"],
        "last_updated": "2026-05-22T10:00:00",
    }
    with patch("backend.mcp_server._load_json_safely", return_value=evo_data):
        res = mcp_server.get_evolution_log()
        assert res["philosophy"] == "phil1"
        assert res["total_entries"] == 2
        assert res["total_philosophies"] == 1
        assert res["last_updated"] == "2026-05-22T10:00:00"


def test_get_evolution_log_empty():
    with patch("backend.mcp_server._load_json_safely", return_value={}):
        res = mcp_server.get_evolution_log()
        assert res["philosophy"] == "未確立"
        assert res["total_entries"] == 0
        assert res["total_philosophies"] == 0
        assert res["latest_entries"] == []


def test_format_pipeline_status_empty():
    res = mcp_server._format_pipeline_status({})
    assert res["status"] == "idle"
    assert res["last_run"] is None


def test_calculate_quality_score():
    review_data = {
        "approved_at": "2026-05-22",
        "stages": [{"completed": True}, {"completed": False}]
    }
    res = mcp_server._calculate_quality_score(review_data)
    assert res["score"] == 50
    assert res["stages_total"] == 2
    assert res["stages_completed"] == 1


def test_summarize_evolution_log():
    evo_data = {
        "entries": ["e1", "e2"],
        "philosophies": ["p1"],
        "last_updated": "2026-05-22"
    }
    res = mcp_server._summarize_evolution_log(evo_data)
    assert res["philosophy"] == "p1"
    assert res["total_entries"] == 2


def test_mcp_server_init_stub_vs_native():
    with patch("backend.mcp_server.logger.info") as mock_logger:
        with patch.dict(sys.modules, {"mcp.server": MagicMock(), "mcp": MagicMock()}):
            server = mcp_server.AntigravityMCPServer()
            assert server._mcp_available is True

        with patch("builtins.__import__", side_effect=ImportError):
            server = mcp_server.AntigravityMCPServer()
            assert server._mcp_available is False


def test_mcp_server_api_methods():
    server = mcp_server.AntigravityMCPServer()

    tools = server.list_tools()
    assert len(tools) == 3
    tool_names = [t["name"] for t in tools]
    assert "get_pipeline_status" in tool_names

    mock_handler = MagicMock(return_value={"status": "ok"})
    with patch.dict(mcp_server.MCP_TOOLS["get_pipeline_status"], {"handler": mock_handler}):
        res = server.call_tool("get_pipeline_status")
        assert res == {"status": "ok"}

    res = server.call_tool("non_existent_tool")
    assert "error" in res

    resources = server.list_resources()
    assert len(resources) == 2
    res_names = [r["name"] for r in resources]
    assert "evolution_log" in res_names

    with patch("backend.mcp_server._load_json_safely") as mock_load:
        mock_load.return_value = {"data": "test"}
        res = server.read_resource("evolution_log")
        assert res == {"data": "test"}

    res = server.read_resource("non_existent_resource")
    assert "error" in res

    info = server.get_server_info()
    assert info["name"] == "antigravity-mcp"
    assert info["tools"] == 3
    assert info["resources"] == 2


def test_fastapi_router():
    from fastapi import FastAPI
    app = FastAPI()
    router = mcp_server.create_mcp_router()
    app.include_router(router)
    client = TestClient(app)

    res = client.get("/mcp/info")
    assert res.status_code == 200
    assert res.json()["name"] == "antigravity-mcp"

    res = client.get("/mcp/tools")
    assert res.status_code == 200
    assert "tools" in res.json()

    mock_handler = MagicMock(return_value={"status": "ok"})
    with patch.dict(mcp_server.MCP_TOOLS["get_pipeline_status"], {"handler": mock_handler}):
        res = client.post("/mcp/tools/get_pipeline_status")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

    res = client.get("/mcp/resources")
    assert res.status_code == 200
    assert "resources" in res.json()

    with patch("backend.mcp_server._load_json_safely") as mock_load:
        mock_load.return_value = {"data": "test"}
        res = client.get("/mcp/resources/evolution_log")
        assert res.status_code == 200
        assert res.json() == {"data": "test"}


def test_standalone_main():
    with patch("backend.mcp_server._load_json_safely", return_value={"entries": [], "philosophies": []}):
        with patch("backend.mcp_server.get_pipeline_status", return_value={}):
            with patch("backend.mcp_server.get_quality_score", return_value={}):
                with patch("builtins.print") as mock_print:
                    mcp_server.main()
                    assert mock_print.called


def test_load_json_invalid_type(tmp_path):
    test_file = tmp_path / "test.json"
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)  # Not a dictionary
    res = mcp_server._load_json_safely(test_file)
    assert res == {}


def test_calculate_quality_score_invalid():
    # Invalid review data structure
    res = mcp_server._calculate_quality_score("invalid_string")
    assert res["score"] is None
    assert "message" in res

    # Stages not a list
    res2 = mcp_server._calculate_quality_score({"stages": "not_a_list"})
    # **見ていないのに 0 点を返さない**（R1.5-C4）。ここは以前 `score == 0` を
    # 期待していたが、それは `round(0 / max(0, 1) * 100)` の産物であって
    # 採点結果ではない。**未計測が「0点・不合格」として出ていた。**
    assert res2["score"] is None
    assert res2["scored"] is False
    assert res2["stages_total"] == 0


def test_summarize_evolution_log_invalid():
    # Invalid evo data structure
    res = mcp_server._summarize_evolution_log("invalid_string")
    assert res["philosophy"] == "未確立"
    assert res["total_entries"] == 0

    # Lists are not lists
    res2 = mcp_server._summarize_evolution_log({"entries": "not_a_list", "philosophies": "not_a_list"})
    assert res2["philosophy"] == "未確立"
    assert res2["total_entries"] == 0


def test_fastapi_router_errors():
    from fastapi import FastAPI
    app = FastAPI()
    router = mcp_server.create_mcp_router()
    app.include_router(router)
    client = TestClient(app)

    # 1. Non-existent tool call
    res = client.post("/mcp/tools/non_existent_tool")
    assert res.status_code == 404

    # 2. Tool execution error (raises TypeError inside call_tool due to wrong arguments)
    mock_handler = MagicMock(side_effect=TypeError("mock type error"))
    with patch.dict(mcp_server.MCP_TOOLS["get_pipeline_status"], {"handler": mock_handler}):
        res = client.post("/mcp/tools/get_pipeline_status")
        assert res.status_code == 400
        assert "TypeError" in res.json()["detail"]

    # 3. Non-existent resource read
    res = client.get("/mcp/resources/non_existent_resource")
    assert res.status_code == 404

