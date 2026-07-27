"""
Unit tests for ToolRegistry in harness/tool_registry.py.
Verifies boundary conditions, mock execution, exception fallbacks, and parameter validations.
"""
import sys
import os
import asyncio
import pytest
from unittest.mock import Mock, patch

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.tool_registry import (
    ToolRegistry, ToolDefinition, ToolResult, ToolAnnotations,
    _python_type_to_json_schema
)


@pytest.mark.anyio
async def test_exception_handling_and_clipping():
    """例外発生時の挙動およびエラーメッセージのクリッピング（500文字制限）を検証"""
    registry = ToolRegistry()

    # 499文字、500文字、501文字のエラーメッセージを生成
    msg_499 = "E" * 499
    msg_500 = "E" * 500
    msg_501 = "E" * 501

    @registry.register(name="err_499", description="499 chars error", input_schema={})
    async def err_499_handler(args):
        raise ValueError(msg_499)

    @registry.register(name="err_500", description="500 chars error", input_schema={})
    async def err_500_handler(args):
        raise ValueError(msg_500)

    @registry.register(name="err_501", description="501 chars error", input_schema={})
    async def err_501_handler(args):
        raise ValueError(msg_501)

    # 1. 499文字のエラー検証
    res_499 = await registry.execute("err_499", {})
    assert res_499.is_error
    expected_499 = f"ツール実行エラー: {msg_499}"
    assert res_499.content[0]["text"] == expected_499
    assert len(res_499.content[0]["text"]) == len("ツール実行エラー: ") + 499

    # 2. 500文字のエラー検証
    res_500 = await registry.execute("err_500", {})
    assert res_500.is_error
    expected_500 = f"ツール実行エラー: {msg_500}"
    assert res_500.content[0]["text"] == expected_500
    assert len(res_500.content[0]["text"]) == len("ツール実行エラー: ") + 500

    # 3. 501文字のエラー検証（500文字でクリップされる）
    res_501 = await registry.execute("err_501", {})
    assert res_501.is_error
    expected_501 = f"ツール実行エラー: {msg_501[:500]}"
    assert res_501.content[0]["text"] == expected_501
    assert len(res_501.content[0]["text"]) == len("ツール実行エラー: ") + 500

    # 統計情報の更新を検証
    stats = registry.get_stats()
    assert stats["tools"]["err_499"]["errors"] == 1
    assert stats["tools"]["err_500"]["errors"] == 1
    assert stats["tools"]["err_501"]["errors"] == 1


@pytest.mark.anyio
async def test_validate_args_poka_yoke():
    """引数バリデーション（Poka-yoke）における境界条件を検証"""
    registry = ToolRegistry()

    @registry.register(
        name="test_poka_yoke",
        description="Poka-yoke test",
        input_schema={
            "video_path": str,
            "file_path": str,
            "path": str,
            "input_path": str,
            "output_path": str,
            "normal_arg": int,
            "opt_arg": "Optional[str]",
            "none_arg": "None",
            "default_arg": {"type": int, "default": 10}
        }
    )
    async def handler(args):
        return args

    # 必須引数が不足している場合のエラー
    res_fail = await registry.execute("test_poka_yoke", {})
    assert res_fail.is_error
    assert "必須引数 'video_path' が不足しています" in res_fail.content[0]["text"]

    # パス引数の相対パスを絶対パスへ自動変換する挙動の検証
    args = {
        "video_path": "relative/video.mp4",
        "file_path": "relative/file.txt",
        "path": "relative/path",
        "input_path": "relative/in",
        "output_path": "relative/out",
        "normal_arg": 42
    }
    res_ok = await registry.execute("test_poka_yoke", args)
    assert not res_ok.is_error
    
    import json
    parsed_args = json.loads(res_ok.content[0]["text"])
    
    assert os.path.isabs(parsed_args["video_path"])
    assert os.path.isabs(parsed_args["file_path"])
    assert os.path.isabs(parsed_args["path"])
    assert os.path.isabs(parsed_args["input_path"])
    assert os.path.isabs(parsed_args["output_path"])
    assert parsed_args["normal_arg"] == 42
    
    # 絶対パスで渡された場合はそのまま維持されることを検証
    abs_path = os.path.abspath("already/absolute.mp4")
    args_abs = {
        "video_path": abs_path,
        "file_path": abs_path,
        "path": abs_path,
        "input_path": abs_path,
        "output_path": abs_path,
        "normal_arg": 99
    }
    res_abs = await registry.execute("test_poka_yoke", args_abs)
    assert not res_abs.is_error
    parsed_abs = json.loads(res_abs.content[0]["text"])
    assert parsed_abs["video_path"] == abs_path


@pytest.mark.anyio
async def test_normalize_result_variants():
    """戻り値正規化の各パターンにおけるフォールバック検証"""
    registry = ToolRegistry()

    # 1. 戻り値がすでに ToolResult オブジェクトの場合
    @registry.register(name="ret_tool_result", description="ToolResult", input_schema={})
    async def handler_tool_result(args):
        return ToolResult(content=[{"type": "text", "text": "custom"}], is_error=True)

    res = await registry.execute("ret_tool_result", {})
    assert res.is_error
    assert res.content[0]["text"] == "custom"

    # 2. 戻り値が MCP準拠の dict（contentキーあり）の場合
    @registry.register(name="ret_mcp_dict", description="MCP dict", input_schema={})
    async def handler_mcp_dict(args):
        return {"content": [{"type": "text", "text": "mcp_content"}], "is_error": False}

    res = await registry.execute("ret_mcp_dict", {})
    assert not res.is_error
    assert res.content[0]["text"] == "mcp_content"

    # 3. 戻り値がエラーstatusを含む dict の場合
    @registry.register(name="ret_err_dict", description="Error dict", input_schema={})
    async def handler_err_dict(args):
        return {"status": "error", "message": "mcp_error_msg"}

    res = await registry.execute("ret_err_dict", {})
    assert res.is_error
    import json
    parsed = json.loads(res.content[0]["text"])
    assert parsed["message"] == "mcp_error_msg"

    # 4. 戻り値が通常の dict の場合
    @registry.register(name="ret_normal_dict", description="Normal dict", input_schema={})
    async def handler_normal_dict(args):
        return {"result": "ok"}

    res = await registry.execute("ret_normal_dict", {})
    assert not res.is_error
    parsed = json.loads(res.content[0]["text"])
    assert parsed["result"] == "ok"

    # 5. 戻り値が JSON 文字列（エラーを含む）の場合
    @registry.register(name="ret_json_err_str", description="JSON error string", input_schema={})
    async def handler_json_err_str(args):
        return '{"status": "error", "error_code": 404}'

    res = await registry.execute("ret_json_err_str", {})
    assert res.is_error
    assert "error_code" in res.content[0]["text"]

    # 6. 戻り値が通常の文字列の場合
    @registry.register(name="ret_plain_str", description="Plain string", input_schema={})
    async def handler_plain_str(args):
        return "plain text message"

    res = await registry.execute("ret_plain_str", {})
    assert not res.is_error
    assert res.content[0]["text"] == "plain text message"

    # 7. 戻り値がその他の型（リストや数値など）の場合
    @registry.register(name="ret_other_types", description="Other types", input_schema={})
    async def handler_other_types(args):
        return [1, 2, 3]

    res = await registry.execute("ret_other_types", {})
    assert not res.is_error
    assert res.content[0]["text"] == "[1, 2, 3]"


@pytest.mark.anyio
async def test_mock_external_api_call_failure():
    """外部 API コール失敗時のモックおよび例外フォールバックの検証"""
    registry = ToolRegistry()

    # 外部依存 API コール（requests 等）を行うダミーツールハンドラー
    @registry.register(
        name="external_api_tool",
        description="External API call tool",
        input_schema={"url": str}
    )
    async def call_external_api(args):
        import requests
        # requests.get を実行してレスポンスを返す（実際にはMock化される）
        response = requests.get(args["url"])
        response.raise_for_status()
        return response.json()

    # 1. 正常系のモック
    mock_response = Mock()
    mock_response.json.return_value = {"status": "success", "data": "value"}
    mock_response.raise_for_status = Mock()

    with patch("requests.get", return_value=mock_response) as mock_get:
        res = await registry.execute("external_api_tool", {"url": "https://api.example.com/v1"})
        assert not res.is_error
        import json
        parsed = json.loads(res.content[0]["text"])
        assert parsed["status"] == "success"
        mock_get.assert_called_once_with("https://api.example.com/v1")

    # 2. 異常系のモック（HTTP 429 Rate Limit やネットワークエラー）
    from requests.exceptions import HTTPError, ConnectionError

    # 2a. HTTP 429 エラー
    mock_err_response = Mock()
    mock_err_response.status_code = 429
    mock_err_response.reason = "Too Many Requests"
    http_error = HTTPError("429 Client Error: Too Many Requests", response=mock_err_response)

    with patch("requests.get", side_effect=http_error):
        res = await registry.execute("external_api_tool", {"url": "https://api.example.com/v1"})
        assert res.is_error
        assert "429 Client Error" in res.content[0]["text"]

    # 2b. ネットワーク接続エラー
    conn_error = ConnectionError("Failed to establish a new connection")
    with patch("requests.get", side_effect=conn_error):
        res = await registry.execute("external_api_tool", {"url": "https://api.example.com/v1"})
        assert res.is_error
        assert "Failed to establish a new connection" in res.content[0]["text"]


@pytest.mark.anyio
async def test_sync_vs_async_handler():
    """同期・非同期ハンドラーが共に正しく実行されることを検証"""
    registry = ToolRegistry()

    # 同期ハンドラー
    @registry.register(name="sync_tool", description="Sync tool", input_schema={"val": int})
    def sync_handler(args):
        return args["val"] * 10

    # 非同期ハンドラー
    @registry.register(name="async_tool", description="Async tool", input_schema={"val": int})
    async def async_handler(args):
        await asyncio.sleep(0.01)
        return args["val"] * 20

    # 同期ハンドラー実行
    res_sync = await registry.execute("sync_tool", {"val": 5})
    assert not res_sync.is_error
    assert res_sync.content[0]["text"] == "50"

    # 非同期ハンドラー実行
    res_async = await registry.execute("async_tool", {"val": 5})
    assert not res_async.is_error
    assert res_async.content[0]["text"] == "100"


@pytest.mark.anyio
async def test_governance_scope_check():
    """ガバナンスにおける権限スコープ検証の境界条件を検証"""
    registry = ToolRegistry()

    @registry.register(
        name="secure_tool",
        description="Secure admin tool",
        input_schema={},
        required_scopes={"write:branding", "admin"}
    )
    async def secure_handler(args):
        return "access_granted"

    # 1. 呼び出しスコープが指定されていない場合はパス（デフォルト許可）
    res_no_scopes = await registry.execute("secure_tool", {})
    assert not res_no_scopes.is_error
    assert res_no_scopes.content[0]["text"] == "access_granted"

    # 2. 呼び出しスコープが不足している場合はエラー
    res_missing_scopes = await registry.execute("secure_tool", {}, caller_scopes={"viewer"})
    assert res_missing_scopes.is_error
    assert "権限不足" in res_missing_scopes.content[0]["text"]

    # 3. 必要なスコープの一部しかない場合もエラー
    res_partial_scopes = await registry.execute("secure_tool", {}, caller_scopes={"admin"})
    assert res_partial_scopes.is_error
    assert "権限不足" in res_partial_scopes.content[0]["text"]

    # 4. 必要なスコープを満たしている場合は成功
    res_granted = await registry.execute("secure_tool", {}, caller_scopes={"admin", "write:branding"})
    assert not res_granted.is_error
    assert res_granted.content[0]["text"] == "access_granted"


def test_python_type_to_json_schema():
    """Python型からJSONスキーマタイプへの変換ヘルパーを検証"""
    assert _python_type_to_json_schema(str) == "string"
    assert _python_type_to_json_schema(int) == "integer"
    assert _python_type_to_json_schema(float) == "number"
    assert _python_type_to_json_schema(bool) == "boolean"
    assert _python_type_to_json_schema(list) == "array"
    assert _python_type_to_json_schema(dict) == "object"
    assert _python_type_to_json_schema(object) == "string"  # マップ外フォールバック

    # dict型のスキーマ定義
    assert _python_type_to_json_schema({"type": int, "default": 20}) == "integer"
    assert _python_type_to_json_schema({"type": str}) == "string"
    assert _python_type_to_json_schema({"other": "field"}) == "string"  # typeキーなし


def test_direct_tool_definition_registration():
    """直接 ToolDefinition を登録する挙動および get_tool / list_tools の検証"""
    registry = ToolRegistry()

    def dummy_handler(args):
        return "direct"

    tool_def = ToolDefinition(
        name="direct_def",
        description="Direct definition tool",
        input_schema={"arg1": str},
        handler=dummy_handler,
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False)
    )

    registry.register_tool(tool_def)
    assert registry.get_tool("direct_def") is tool_def

    # list_tools レスポンスの検証
    tools = registry.list_tools()
    target = None
    for t in tools:
        if t["name"] == f"mcp__{registry._server_name}__direct_def":
            target = t
            break

    assert target is not None
    assert target["description"] == "Direct definition tool"
    assert target["inputSchema"]["properties"]["arg1"]["type"] == "string"
    assert target["annotations"]["readOnlyHint"] is True
    assert target["annotations"]["destructiveHint"] is False


@pytest.mark.anyio
async def test_nonexistent_tool_execution():
    """存在しないツールを実行した場合の挙動を検証"""
    registry = ToolRegistry()
    res = await registry.execute("nonexistent", {})
    assert res.is_error
    assert "ツール 'nonexistent' が見つかりません" in res.content[0]["text"]


@pytest.mark.anyio
async def test_decorator_direct_call():
    """デコレータ登録された wrapper の直接呼び出し (L157 のカバレッジカバー) """
    registry = ToolRegistry()

    @registry.register(name="direct_call_test", description="Direct call test", input_schema={})
    async def direct_call_handler(args):
        return "executed_direct"

    # wrapper を直接呼び出し
    res = await direct_call_handler({})
    assert res == "executed_direct"


@pytest.mark.anyio
async def test_sync_handler_exception_handling():
    """同期ハンドラーが例外をスローした場合の挙動検証"""
    registry = ToolRegistry()

    @registry.register(name="sync_error_tool", description="Sync error test", input_schema={})
    def sync_error_handler(args):
        raise ValueError("Sync execution failed")

    res = await registry.execute("sync_error_tool", {})
    assert res.is_error
    assert "Sync execution failed" in res.content[0]["text"]
    assert registry.get_tool("sync_error_tool").error_count == 1


def test_validate_args_more_boundaries():
    """引数バリデーション（Poka-yoke）のさらなる境界条件"""
    registry = ToolRegistry()

    # 1. デフォルト値を持つ引数スキーマの定義 (dict形式)
    # 2. None / Optional を含むスキーマ定義
    @registry.register(
        name="boundary_poka_yoke",
        description="Boundary poka-yoke test",
        input_schema={
            "required_val": int,
            "default_val": {"type": int, "default": 100},
            "opt_val": "Optional[int]",
            "none_val": "None"
        }
    )
    def dummy(args):
        return args

    # 必須引数が足りない場合はエラー
    res_err = registry._validate_args(registry.get_tool("boundary_poka_yoke"), {})
    assert "必須引数 'required_val' が不足しています" in res_err

    # デフォルト値あり、または Optional / None が不足していても required_val があればパスする
    res_ok = registry._validate_args(registry.get_tool("boundary_poka_yoke"), {"required_val": 42})
    assert res_ok is None


@pytest.mark.anyio
async def test_validate_args_empty_path():
    """パス引数が空文字列の場合にPoka-yokeが安全にスキップされることを検証"""
    registry = ToolRegistry()

    @registry.register(
        name="empty_path_tool",
        description="Empty path test",
        input_schema={"video_path": str}
    )
    def dummy(args):
        return args

    # 空文字列の場合、Path(path_val).is_absolute()は評価されず、エラーも起きないこと
    args = {"video_path": ""}
    res = await registry.execute("empty_path_tool", args)
    assert not res.is_error
    import json
    parsed = json.loads(res.content[0]["text"])
    assert parsed["video_path"] == ""


def test_tool_re_registration():
    """同一ツール名の多重登録（上書き）を検証"""
    registry = ToolRegistry()

    @registry.register(name="re_reg_tool", description="First registration", input_schema={})
    def first(args):
        return "first"

    assert registry.get_tool("re_reg_tool").description == "First registration"

    @registry.register(name="re_reg_tool", description="Second registration", input_schema={})
    def second(args):
        return "second"

    assert registry.get_tool("re_reg_tool").description == "Second registration"


def test_python_type_to_json_schema_unknown_types():
    """未知のクラス型や、スキーマ定義内での未知の型が string にフォールバックされることを検証"""
    class CustomClass:
        pass

    assert _python_type_to_json_schema(CustomClass) == "string"
    assert _python_type_to_json_schema({"type": CustomClass}) == "string"


@pytest.mark.anyio
async def test_stats_calculation_and_averages():
    """統計情報の call_count, error_count, avg_duration_s 等の集計ロジックを検証"""
    registry = ToolRegistry()

    @registry.register(name="stats_tool", description="Stats test", input_schema={})
    async def stats_handler(args):
        await asyncio.sleep(0.01)
        if args.get("fail"):
            raise ValueError("Failure")
        return "ok"

    # 初期状態
    tool = registry.get_tool("stats_tool")
    assert tool.call_count == 0
    assert tool.error_count == 0

    # 1回目：成功
    await registry.execute("stats_tool", {"fail": False})
    assert tool.call_count == 1
    assert tool.error_count == 0
    assert tool.total_duration_seconds > 0

    # 2回目：失敗
    await registry.execute("stats_tool", {"fail": True})
    assert tool.call_count == 1  # 失敗時は call_count は増えない
    assert tool.error_count == 1

    # get_stats の出力を検証
    stats = registry.get_stats()
    tool_stats = stats["tools"]["stats_tool"]
    assert tool_stats["calls"] == 1
    assert tool_stats["errors"] == 1
    assert "avg_duration_s" in tool_stats

@pytest.mark.anyio
async def test_uncaught_exceptions_fail_fast():
    """キャッチ対象外の例外（例: ZeroDivisionError, IndexError）が発生した際、ツールレジストリがそれをキャッチせずそのままスローされることを検証 (Fail Fast)"""
    registry = ToolRegistry()

    @registry.register(name="zero_div_tool", description="Zero division test", input_schema={})
    async def zero_div_handler(args):
        return 1 / 0

    @registry.register(name="index_err_tool", description="Index error test", input_schema={})
    def index_err_handler(args):
        lst = []
        return lst[0]

    # 1. ZeroDivisionError がそのまま送出されることを検証
    with pytest.raises(ZeroDivisionError):
        await registry.execute("zero_div_tool", {})

    # 2. IndexError がそのまま送出されることを検証
    with pytest.raises(IndexError):
        await registry.execute("index_err_tool", {})

