import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.mcp_server as mcp

# ============================================================
# 1. 内部ヘルパー関数のテスト
# ============================================================

def test_load_json_safely_success(tmp_path):
    test_file = tmp_path / "test.json"
    data = {"key": "value"}
    test_file.write_text(json.dumps(data), encoding="utf-8")
    
    res = mcp._load_json_safely(test_file)
    assert res == data

def test_load_json_safely_not_exists():
    res = mcp._load_json_safely(Path("non_existent_file_xyz.json"))
    assert res == {}

def test_load_json_safely_not_dict(tmp_path, caplog):
    test_file = tmp_path / "test_list.json"
    test_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        res = mcp._load_json_safely(test_file)
    assert res == {}
    assert "is not a dictionary" in caplog.text

def test_load_json_safely_invalid_json(tmp_path, caplog):
    test_file = tmp_path / "invalid.json"
    test_file.write_text("{invalid json", encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        res = mcp._load_json_safely(test_file)
    assert res == {}
    assert "Failed to load" in caplog.text

def test_format_pipeline_status_empty():
    res = mcp._format_pipeline_status({})
    assert res["status"] == "idle"
    assert res["message"] == "パイプラインは待機中です"
    assert res["last_run"] is None

def test_format_pipeline_status_valid():
    input_data = {
        "status": "running",
        "current_stage": "encoding",
        "progress": 50,
        "video_file": "output.mp4",
        "started_at": "2026-06-23T07:00:00Z",
        "stages_completed": 3,
    }
    res = mcp._format_pipeline_status(input_data)
    assert res["status"] == "running"
    assert res["current_stage"] == "encoding"
    assert res["progress"] == 50
    assert res["video_file"] == "output.mp4"
    assert res["started_at"] == "2026-06-23T07:00:00Z"
    assert res["stages_completed"] == 3

def test_calculate_quality_score_invalid():
    res = mcp._calculate_quality_score(None)
    assert res["score"] is None
    assert "無効なデータ形式" in res["message"]

def test_calculate_quality_score_no_stages():
    res = mcp._calculate_quality_score({})
    # **見ていないのに 0 点を返さない**（R1.5-C4）。ここは以前 `score == 0` を
    # 期待していたが、それは `round(0 / max(0, 1) * 100)` の産物であって
    # 採点結果ではない。**未計測が「0点・不合格」として出ていた。**
    assert res["score"] is None
    assert res["scored"] is False
    assert res["stages_total"] == 0
    assert res["stages_completed"] == 0

def test_calculate_quality_score_non_list_stages():
    res = mcp._calculate_quality_score({"stages": "not a list"})
    # **見ていないのに 0 点を返さない**（R1.5-C4）。ここは以前 `score == 0` を
    # 期待していたが、それは `round(0 / max(0, 1) * 100)` の産物であって
    # 採点結果ではない。**未計測が「0点・不合格」として出ていた。**
    assert res["score"] is None
    assert res["scored"] is False
    assert res["stages_total"] == 0
    assert res["stages_completed"] == 0

def test_calculate_quality_score_success():
    review_data = {
        "stages": [
            {"name": "stage1", "completed": True},
            {"name": "stage2", "completed": False},
            {"name": "stage3", "completed": True},
        ],
        "approved_at": "2026-06-23T07:10:00Z"
    }
    res = mcp._calculate_quality_score(review_data)
    assert res["score"] == 67  # round(2/3 * 100) = 67
    assert res["stages_total"] == 3
    assert res["stages_completed"] == 2
    assert res["approved_at"] == "2026-06-23T07:10:00Z"

def test_summarize_evolution_log_invalid():
    res = mcp._summarize_evolution_log(None)
    assert res["philosophy"] == "未確立"
    assert res["total_entries"] == 0

def test_summarize_evolution_log_empty():
    res = mcp._summarize_evolution_log({})
    assert res["philosophy"] == "未確立"
    assert res["total_entries"] == 0
    assert res["total_philosophies"] == 0
    assert res["latest_entries"] == []

def test_summarize_evolution_log_non_list():
    res = mcp._summarize_evolution_log({"entries": "not list", "philosophies": "not list"})
    assert res["philosophy"] == "未確立"
    assert res["total_entries"] == 0
    assert res["total_philosophies"] == 0

def test_summarize_evolution_log_success():
    evo_data = {
        "philosophies": ["Philosophy A", "Philosophy B"],
        "entries": [1, 2, 3, 4, 5, 6],
        "last_updated": "2026-06-23T07:20:00Z"
    }
    res = mcp._summarize_evolution_log(evo_data)
    assert res["philosophy"] == "Philosophy B"
    assert res["total_entries"] == 6
    assert res["total_philosophies"] == 2
    assert res["latest_entries"] == [2, 3, 4, 5, 6]  # latest 5
    assert res["last_updated"] == "2026-06-23T07:20:00Z"

# ============================================================
# 2. データ取得・ファイルアクセスのテスト
# ============================================================

@patch("backend.mcp_server._load_json_safely")
def test_get_pipeline_status_call(mock_load):
    mock_load.return_value = {"status": "processing", "progress": 80}
    res = mcp.get_pipeline_status()
    assert res["status"] == "processing"
    assert res["progress"] == 80

@patch("backend.mcp_server.Path.exists")
def test_get_quality_score_not_exists(mock_exists):
    mock_exists.return_value = False
    res = mcp.get_quality_score()
    assert res["score"] is None
    assert "品質スコアはまだ記録されていません" in res["message"]

@patch("backend.mcp_server.Path.exists")
@patch("builtins.open", new_callable=mock_open, read_data='{"stages": [{"completed": true}], "approved_at": "2026-06-23T07:10:00Z"}\n')
def test_get_quality_score_success(mock_file, mock_exists):
    mock_exists.return_value = True
    res = mcp.get_quality_score()
    assert res["score"] == 100

@patch("backend.mcp_server.Path.exists")
@patch("builtins.open", new_callable=mock_open, read_data='{invalid json\n')
def test_get_quality_score_invalid_json(mock_file, mock_exists):
    mock_exists.return_value = True
    res = mcp.get_quality_score()
    assert res["score"] is None
    assert "解析エラー" in res["message"]

@patch("backend.mcp_server._load_json_safely")
def test_get_evolution_log_call(mock_load):
    mock_load.return_value = {"philosophies": ["Philosophy Alpha"], "entries": [1]}
    res = mcp.get_evolution_log()
    assert res["philosophy"] == "Philosophy Alpha"
    assert res["total_entries"] == 1

# ============================================================
# 3. AntigravityMCPServer クラスのテスト
# ============================================================

def test_server_init_stub_mode():
    with patch.dict("sys.modules", {"mcp.server": None}):
        server = mcp.AntigravityMCPServer()
        assert server._mcp_available is False

def test_server_init_native_mode():
    mock_server_mod = MagicMock()
    with patch.dict("sys.modules", {"mcp.server": mock_server_mod}):
        server = mcp.AntigravityMCPServer()
        assert server._mcp_available is True

def test_list_tools():
    server = mcp.AntigravityMCPServer()
    tools = server.list_tools()
    assert len(tools) == 3
    tool_names = [t["name"] for t in tools]
    assert "get_pipeline_status" in tool_names
    assert "get_quality_score" in tool_names
    assert "get_evolution_log" in tool_names

def test_call_tool_success():
    server = mcp.AntigravityMCPServer()
    mock_handler = MagicMock(return_value={"status": "success"})
    with patch.dict(server.tools, {"get_pipeline_status": {**server.tools["get_pipeline_status"], "handler": mock_handler}}):
        res = server.call_tool("get_pipeline_status")
        assert res == {"status": "success"}
        mock_handler.assert_called_once()

def test_call_tool_unknown():
    server = mcp.AntigravityMCPServer()
    res = server.call_tool("unknown_tool")
    assert "Unknown tool" in res["error"]

def test_call_tool_error():
    server = mcp.AntigravityMCPServer()
    mock_handler = MagicMock(side_effect=TypeError("invalid argument"))
    with patch.dict(server.tools, {"get_pipeline_status": {**server.tools["get_pipeline_status"], "handler": mock_handler}}):
        res = server.call_tool("get_pipeline_status")
        assert "Tool execution failed" in res["error"]

def test_list_resources():
    server = mcp.AntigravityMCPServer()
    resources = server.list_resources()
    assert len(resources) == 2
    res_names = [r["name"] for r in resources]
    assert "evolution_log" in res_names
    assert "constitution" in res_names

def test_read_resource_success():
    server = mcp.AntigravityMCPServer()
    with patch("backend.mcp_server._load_json_safely") as mock_load:
        mock_load.return_value = {"data": "mocked"}
        res = server.read_resource("evolution_log")
        assert res == {"data": "mocked"}

def test_read_resource_unknown():
    server = mcp.AntigravityMCPServer()
    res = server.read_resource("unknown_resource")
    assert "Unknown resource" in res["error"]

def test_read_resource_error():
    server = mcp.AntigravityMCPServer()
    with patch("backend.mcp_server._load_json_safely", side_effect=OSError("disk error")):
        res = server.read_resource("evolution_log")
        assert "Resource read failed" in res["error"]

def test_get_server_info():
    server = mcp.AntigravityMCPServer()
    info = server.get_server_info()
    assert info["name"] == "antigravity-mcp"
    assert info["tools"] == 3
    assert info["resources"] == 2

# ============================================================
# 4. リソースローダー (ラムダ式) のテスト
# ============================================================

@patch("backend.mcp_server._load_json_safely")
def test_resource_loaders(mock_load):
    mock_load.return_value = {"loaded": True}
    
    loader_evo = mcp.MCP_RESOURCES["evolution_log"]["loader"]
    assert loader_evo() == {"loaded": True}
    
    loader_const = mcp.MCP_RESOURCES["constitution"]["loader"]
    assert loader_const() == {"loaded": True}

# ============================================================
# 5. FastAPI ルーター (create_mcp_router) のテスト
# ============================================================

def test_create_mcp_router():
    from fastapi import FastAPI
    app = FastAPI()
    router = mcp.create_mcp_router()
    app.include_router(router)
    client = TestClient(app)
    
    # 1. /mcp/info のテスト
    response = client.get("/mcp/info")
    assert response.status_code == 200
    assert response.json()["name"] == "antigravity-mcp"
    
    # 2. /mcp/tools のテスト
    response = client.get("/mcp/tools")
    assert response.status_code == 200
    assert "tools" in response.json()
    
    # 3. /mcp/tools/{tool_name} のテスト (正常系)
    mock_handler = MagicMock(return_value={"status": "ok"})
    with patch.dict(mcp.mcp_server.tools, {"get_pipeline_status": {**mcp.mcp_server.tools["get_pipeline_status"], "handler": mock_handler}}):
        response = client.post("/mcp/tools/get_pipeline_status", json={})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        
    # 4. /mcp/tools/{tool_name} (存在しないツール)
    response = client.post("/mcp/tools/non_existent_tool")
    assert response.status_code == 404
    
    # 5. /mcp/tools/{tool_name} (エラー発生時の400)
    mock_handler_err = MagicMock(side_effect=TypeError("error"))
    with patch.dict(mcp.mcp_server.tools, {"get_pipeline_status": {**mcp.mcp_server.tools["get_pipeline_status"], "handler": mock_handler_err}}):
        response = client.post("/mcp/tools/get_pipeline_status", json={})
        assert response.status_code == 400
        assert "Tool execution failed" in response.json()["detail"]
        
    # 6. /mcp/resources のテスト
    response = client.get("/mcp/resources")
    assert response.status_code == 200
    assert "resources" in response.json()
    
    # 7. /mcp/resources/{resource_name} のテスト (正常系)
    with patch("backend.mcp_server._load_json_safely") as mock_load:
        mock_load.return_value = {"data": 123}
        response = client.get("/mcp/resources/evolution_log")
        assert response.status_code == 200
        assert response.json() == {"data": 123}
        
    # 8. /mcp/resources/{resource_name} (存在しないリソース)
    response = client.get("/mcp/resources/non_existent_resource")
    assert response.status_code == 404
    
    # 9. /mcp/resources/{resource_name} (エラー発生時の400)
    with patch("backend.mcp_server._load_json_safely", side_effect=OSError("error")):
        response = client.get("/mcp/resources/evolution_log")
        assert response.status_code == 400
        assert "Resource read failed" in response.json()["detail"]

# ============================================================
# 6. main 関数のテスト
# ============================================================

@patch("builtins.print")
@patch("backend.mcp_server.get_pipeline_status")
@patch("backend.mcp_server.get_quality_score")
@patch("backend.mcp_server.get_evolution_log")
@patch("backend.mcp_server._load_json_safely")
def test_main(mock_load, mock_get_evo, mock_get_qual, mock_get_pipe, mock_print):
    mock_get_pipe.return_value = {"status": "ok"}
    mock_get_qual.return_value = {"score": 90}
    mock_get_evo.return_value = {"philosophy": "test"}
    mock_load.return_value = {"loaded": True}
    
    mcp.main()
    
    # printが呼び出されていることを確認
    mock_print.assert_any_call("Antigravity MCP Server")
    mock_print.assert_any_call("--- Tool Test ---")
    mock_print.assert_any_call("--- Resource Test ---")


# ============================================================
# 7. 追加のエッジケース・例外処理テスト (カバレッジ堅牢性の向上)
# ============================================================

def test_load_json_safely_empty_file(tmp_path, caplog):
    test_file = tmp_path / "empty.json"
    test_file.write_text("", encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        res = mcp._load_json_safely(test_file)
    assert res == {}
    assert "Failed to load" in caplog.text

def test_load_json_safely_non_dict_val(tmp_path, caplog):
    test_file = tmp_path / "null.json"
    test_file.write_text("null", encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        res = mcp._load_json_safely(test_file)
    assert res == {}
    assert "is not a dictionary" in caplog.text

def test_calculate_quality_score_invalid_stage_element():
    # stagesリスト内に辞書型以外の無効な要素（Noneや文字列、数値など）が含まれている場合
    review_data = {
        "stages": [
            {"name": "stage1", "completed": True},
            None,
            "invalid_stage_str",
            123,
            {"name": "stage2", "completed": False}
        ]
    }
    res = mcp._calculate_quality_score(review_data)
    assert res["score"] == 20  # completed=1, total=5 -> 1/5 * 100 = 20
    assert res["stages_total"] == 5
    assert res["stages_completed"] == 1

def test_calculate_quality_score_no_completed_key():
    # completedキーが含まれていない場合のデフォルト処理
    review_data = {
        "stages": [
            {"name": "stage1"},
            {"name": "stage2", "completed": True}
        ]
    }
    res = mcp._calculate_quality_score(review_data)
    assert res["score"] == 50
    assert res["stages_total"] == 2
    assert res["stages_completed"] == 1

def test_summarize_evolution_log_missing_keys():
    # philosophies や entries キー自体が存在しない場合
    res = mcp._summarize_evolution_log({"last_updated": "2026-06-23T07:20:00Z"})
    assert res["philosophy"] == "未確立"
    assert res["total_entries"] == 0
    assert res["total_philosophies"] == 0
    assert res["latest_entries"] == []
    assert res["last_updated"] == "2026-06-23T07:20:00Z"

def test_summarize_evolution_log_less_than_five_entries():
    # entries の件数が 5 件未満の場合
    evo_data = {
        "philosophies": ["Philosophy A"],
        "entries": [1, 2, 3]
    }
    res = mcp._summarize_evolution_log(evo_data)
    assert res["philosophy"] == "Philosophy A"
    assert res["total_entries"] == 3
    assert res["latest_entries"] == [1, 2, 3]

@patch("backend.mcp_server.Path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="")
def test_get_quality_score_empty_file(mock_file, mock_exists):
    # review_approvals.jsonl が存在するが空（0行）の場合
    mock_exists.return_value = True
    res = mcp.get_quality_score()
    assert res["score"] is None
    assert "解析エラー" in res["message"]

@patch("backend.mcp_server.Path.exists")
def test_get_quality_score_os_error(mock_exists):
    # ファイル読み込み時に OSError が発生した場合
    mock_exists.return_value = True
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        res = mcp.get_quality_score()
    assert res["score"] is None
    assert "解析エラー" in res["message"]

def test_call_tool_key_error():
    # call_tool で KeyError などの例外が発生した場合のハンドリング
    server = mcp.AntigravityMCPServer()
    mock_handler = MagicMock(side_effect=KeyError("dummy key"))
    with patch.dict(server.tools, {"get_pipeline_status": {**server.tools["get_pipeline_status"], "handler": mock_handler}}):
        res = server.call_tool("get_pipeline_status")
        assert "Tool execution failed" in res["error"]
        assert "KeyError" in res["error"]

def test_read_resource_value_error():
    # read_resource で ValueError などの例外が発生した場合
    server = mcp.AntigravityMCPServer()
    with patch("backend.mcp_server._load_json_safely", side_effect=ValueError("dummy value error")):
        res = server.read_resource("evolution_log")
        assert "Resource read failed" in res["error"]
        assert "ValueError" in res["error"]

def test_router_call_tool_invalid_args():
    # FastAPI ルーター経由で call_tool が失敗（400エラー）するケース
    from fastapi import FastAPI
    app = FastAPI()
    router = mcp.create_mcp_router()
    app.include_router(router)
    client = TestClient(app)
    
    mock_handler = MagicMock(side_effect=ValueError("dummy error"))
    with patch.dict(mcp.mcp_server.tools, {"get_pipeline_status": {**mcp.mcp_server.tools["get_pipeline_status"], "handler": mock_handler}}):
        response = client.post("/mcp/tools/get_pipeline_status", json={})
        assert response.status_code == 400
        assert "ValueError" in response.json()["detail"]
