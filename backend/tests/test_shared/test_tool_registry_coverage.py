import pytest
import os
import asyncio
from pathlib import Path
from unittest.mock import MagicMock
from harness.tool_registry import (
    ToolRegistry, ToolDefinition, ToolAnnotations, ToolResult,
    _python_type_to_json_schema, tool_registry
)

# 1. データ構造のテスト
def test_tool_annotations():
    anno = ToolAnnotations()
    assert anno.readOnlyHint is False
    assert anno.destructiveHint is False
    assert anno.idempotentHint is True
    assert anno.openWorldHint is False

    custom_anno = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True
    )
    assert custom_anno.readOnlyHint is True
    assert custom_anno.destructiveHint is True
    assert custom_anno.idempotentHint is False
    assert custom_anno.openWorldHint is True

def test_tool_definition():
    async def dummy_handler(args):
        return {}
    
    td = ToolDefinition(
        name="test",
        description="test desc",
        input_schema={"param": str},
        handler=dummy_handler
    )
    assert td.name == "test"
    assert td.description == "test desc"
    assert td.input_schema == {"param": str}
    assert td.handler == dummy_handler
    assert td.annotations.idempotentHint is True
    assert td.call_count == 0
    assert td.total_duration_seconds == 0.0
    assert td.error_count == 0

def test_tool_result():
    tr = ToolResult(content=[{"type": "text", "text": "hello"}])
    assert tr.content == [{"type": "text", "text": "hello"}]
    assert tr.is_error is False
    assert tr.duration_seconds == 0.0
    assert tr.tool_name == ""

# 2. ツール登録機能のテスト
@pytest.mark.asyncio
async def test_register_decorator():
    registry = ToolRegistry()

    @registry.register(
        name="sync_echo",
        description="同期エコーツール",
        input_schema={"message": str},
        annotations={"readOnlyHint": True},
        examples=[{"message": "hello"}],
        error_hints=["invalid msg"],
        required_scopes={"read"}
    )
    async def sync_echo(args):
        return f"Echo: {args['message']}"

    assert "sync_echo" in registry._tools
    tool_def = registry.get_tool("sync_echo")
    assert tool_def is not None
    assert tool_def.description == "同期エコーツール"
    assert tool_def.annotations.readOnlyHint is True
    assert tool_def.examples == [{"message": "hello"}]
    assert tool_def.error_hints == ["invalid msg"]
    assert tool_def.required_scopes == {"read"}

    # ラッパーの呼び出しテスト
    res = await sync_echo({"message": "hello"})
    assert res == "Echo: hello"
    assert hasattr(sync_echo, "_tool_definition")
    assert sync_echo._tool_definition == tool_def

def test_register_tool_direct():
    registry = ToolRegistry()
    def dummy(args):
        return {}
    tool_def = ToolDefinition(
        name="direct_tool",
        description="直接登録ツール",
        input_schema={},
        handler=dummy
    )
    registry.register_tool(tool_def)
    assert "direct_tool" in registry._tools
    assert registry.get_tool("direct_tool") == tool_def

# 3. ツール実行のテスト
@pytest.mark.asyncio
async def test_execute_nonexistent_tool():
    registry = ToolRegistry()
    result = await registry.execute("no_such_tool", {})
    assert result.is_error is True
    assert "が見つかりません" in result.content[0]["text"]
    assert result.tool_name == "no_such_tool"

@pytest.mark.asyncio
async def test_execute_governance_scopes():
    registry = ToolRegistry()

    @registry.register(
        name="secured_tool",
        description="要権限ツール",
        input_schema={},
        required_scopes={"admin", "write"}
    )
    async def secured_tool(args):
        return "success"

    # caller_scopes が None の場合はスコープ検証をスキップ
    res1 = await registry.execute("secured_tool", {}, caller_scopes=None)
    assert res1.is_error is False
    assert res1.content[0]["text"] == "success"

    # caller_scopes が不足している場合
    res2 = await registry.execute("secured_tool", {}, caller_scopes={"read"})
    assert res2.is_error is True
    assert "権限不足" in res2.content[0]["text"]

    # caller_scopes が十分な場合
    res3 = await registry.execute("secured_tool", {}, caller_scopes={"admin", "write", "read"})
    assert res3.is_error is False
    assert res3.content[0]["text"] == "success"

@pytest.mark.asyncio
async def test_execute_validate_args():
    registry = ToolRegistry()

    @registry.register(
        name="validated_tool",
        description="引数検証ツール",
        input_schema={
            "required_str": str,
            "optional_val": "Optional[int]",
            "default_dict": {"type": int, "default": 10},
            "none_val": "None"
        }
    )
    async def validated_tool(args):
        return "success"

    # 必須引数が不足している場合
    res1 = await registry.execute("validated_tool", {})
    assert res1.is_error is True
    assert "必須引数 'required_str' が不足しています" in res1.content[0]["text"]

    # 必須引数はあるが、Optionalやdefault付きの引数がない場合（バリデーションをパスするべき）
    res2 = await registry.execute("validated_tool", {"required_str": "hello"})
    assert res2.is_error is False
    assert res2.content[0]["text"] == "success"

@pytest.mark.asyncio
async def test_execute_poka_yoke_path_normalization():
    registry = ToolRegistry()

    @registry.register(
        name="path_tool",
        description="パス検証ツール",
        input_schema={
            "video_path": str,
            "file_path": str,
            "path": str,
            "input_path": str,
            "output_path": str
        }
    )
    async def path_tool(args):
        return args

    # 相対パスが自動で絶対パスに変換されることを確認
    args = {
        "video_path": "rel/video.mp4",
        "file_path": "rel/file.txt",
        "path": "rel/dir",
        "input_path": "rel/in",
        "output_path": "rel/out"
    }
    res = await registry.execute("path_tool", args)
    assert res.is_error is False
    normalized_args = eval(res.content[0]["text"]) # normalized_resultでjson.dumpsされたdictを復元
    for key in args.keys():
        assert Path(normalized_args[key]).is_absolute()
        assert normalized_args[key] == str(Path(args[key]).resolve())

    # 既に絶対パスの場合はそのまま
    abs_path = str(Path("/absolute/path/file.mp4").resolve())
    args_abs = {
        "video_path": abs_path,
        "file_path": abs_path,
        "path": abs_path,
        "input_path": abs_path,
        "output_path": abs_path
    }
    res_abs = await registry.execute("path_tool", args_abs)
    normalized_args_abs = eval(res_abs.content[0]["text"])
    for key in args_abs.keys():
        assert normalized_args_abs[key] == abs_path

@pytest.mark.asyncio
async def test_execute_exception_handling():
    registry = ToolRegistry()

    @registry.register(
        name="buggy_tool",
        description="例外スローツール",
        input_schema={}
    )
    async def buggy_tool(args):
        raise ValueError("内部で致命的なエラーが発生しました")

    res = await registry.execute("buggy_tool", {})
    assert res.is_error is True
    assert "ツール実行エラー" in res.content[0]["text"]
    assert "内部で致命的なエラーが発生しました" in res.content[0]["text"]
    
    stats = registry.get_stats()
    assert stats["tools"]["buggy_tool"]["errors"] == 1

@pytest.mark.asyncio
async def test_execute_sync_handler():
    registry = ToolRegistry()

    @registry.register(
        name="sync_tool",
        description="同期ハンドラ",
        input_schema={}
    )
    def sync_tool(args):
        return "sync ok"

    res = await registry.execute("sync_tool", {})
    assert res.is_error is False
    assert res.content[0]["text"] == "sync ok"

# 4. 結果の正規化のテスト
def test_normalize_result():
    registry = ToolRegistry()

    # 1) ToolResult の直接返却
    tr = ToolResult(content=[{"type": "text", "text": "result_obj"}], is_error=True)
    res1 = registry._normalize_result(tr, "tool_name", 1.5)
    assert res1 == tr
    assert res1.duration_seconds == 1.5
    assert res1.tool_name == "tool_name"

    # 2) dict返却（contentキーあり）
    res2 = registry._normalize_result(
        {"content": [{"type": "text", "text": "dict_content"}], "is_error": True},
        "tool_name",
        1.5
    )
    assert res2.content == [{"type": "text", "text": "dict_content"}]
    assert res2.is_error is True
    assert res2.duration_seconds == 1.5
    assert res2.tool_name == "tool_name"

    # 3) dict返却（status == "error"）
    res3 = registry._normalize_result(
        {"status": "error", "message": "something wrong"},
        "tool_name",
        1.5
    )
    assert res3.is_error is True
    assert "something wrong" in res3.content[0]["text"]

    # 4) dict返却（通常）
    res4 = registry._normalize_result(
        {"status": "ok", "value": 42},
        "tool_name",
        1.5
    )
    assert res4.is_error is False
    assert "42" in res4.content[0]["text"]

    # 5) str返却（JSONパース成功、status == "error" を含む）
    res5 = registry._normalize_result(
        '{"status": "error", "msg": "json_err"}',
        "tool_name",
        1.5
    )
    assert res5.is_error is True
    assert "json_err" in res5.content[0]["text"]

    # 6) str返却（JSONパース成功、status == "error" を含まない）
    res5_ok = registry._normalize_result(
        '{"status": "success", "msg": "json_ok"}',
        "tool_name",
        1.5
    )
    assert res5_ok.is_error is False
    assert "json_ok" in res5_ok.content[0]["text"]

    # 7) str返却（JSONパース失敗）
    res6 = registry._normalize_result(
        "plain text message",
        "tool_name",
        1.5
    )
    assert res6.is_error is False
    assert res6.content[0]["text"] == "plain text message"

    # 8) その他の型返却
    res7 = registry._normalize_result(
        999,
        "tool_name",
        1.5
    )
    assert res7.is_error is False
    assert res7.content[0]["text"] == "999"

# 5. ツール検索・一覧・統計のテスト
def test_list_tools_schema_conversion():
    registry = ToolRegistry()

    @registry.register(
        name="typed_tool",
        description="型アノテーション確認",
        input_schema={
            "s": str,
            "i": int,
            "f": float,
            "b": bool,
            "l": list,
            "d": dict,
            "custom_dict": {"type": float, "default": 1.0},
            "unknown": object
        }
    )
    def typed_tool(args):
        pass

    tools = registry.list_tools()
    assert len(tools) == 1
    t = tools[0]
    assert t["name"] == "mcp__antigravity_pipeline__typed_tool"
    assert t["description"] == "型アノテーション確認"
    
    props = t["inputSchema"]["properties"]
    assert props["s"]["type"] == "string"
    assert props["i"]["type"] == "integer"
    assert props["f"]["type"] == "number"
    assert props["b"]["type"] == "boolean"
    assert props["l"]["type"] == "array"
    assert props["d"]["type"] == "object"
    assert props["custom_dict"]["type"] == "number"
    assert props["unknown"]["type"] == "string" # fallback

@pytest.mark.asyncio
async def test_stats_summary():
    registry = ToolRegistry()

    @registry.register(
        name="stat_tool",
        description="統計ツール",
        input_schema={}
    )
    async def stat_tool(args):
        await asyncio.sleep(0.01)
        return "ok"

    # 実行前統計
    stats = registry.get_stats()
    assert stats["tool_count"] == 1
    assert stats["tools"]["stat_tool"]["calls"] == 0

    # 実行後統計
    await registry.execute("stat_tool", {})
    stats2 = registry.get_stats()
    assert stats2["tools"]["stat_tool"]["calls"] == 1
    assert stats2["tools"]["stat_tool"]["total_duration_s"] >= 0.0
    assert stats2["tools"]["stat_tool"]["avg_duration_s"] >= 0.0

def test_python_type_to_json_schema():
    assert _python_type_to_json_schema(str) == "string"
    assert _python_type_to_json_schema(int) == "integer"
    assert _python_type_to_json_schema(float) == "number"
    assert _python_type_to_json_schema(bool) == "boolean"
    assert _python_type_to_json_schema(list) == "array"
    assert _python_type_to_json_schema(dict) == "object"
    assert _python_type_to_json_schema(object) == "string"
    assert _python_type_to_json_schema({"type": int}) == "integer"
    assert _python_type_to_json_schema({"type": float, "default": 2.0}) == "number"
    assert _python_type_to_json_schema({"type": object}) == "string"

def test_singleton_registry():
    assert isinstance(tool_registry, ToolRegistry)
