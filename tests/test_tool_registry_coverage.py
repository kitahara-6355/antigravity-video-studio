import pytest
import asyncio
from pathlib import Path
from harness.tool_registry import ToolRegistry, ToolDefinition, ToolResult, ToolAnnotations

@pytest.fixture
def registry():
    return ToolRegistry()

@pytest.mark.asyncio
async def test_decorator_wrapper_execution(registry):
    @registry.register(
        name="test_tool",
        description="test tool description",
        input_schema={"val": int}
    )
    async def my_tool(args):
        return {"result": args["val"] * 2}

    res = await my_tool({"val": 5})
    assert res == {"result": 10}
    
    exec_res = await registry.execute("test_tool", {"val": 5})
    assert exec_res.is_error is False
    assert exec_res.content[0]["text"] == '{"result": 10}'

def test_register_tool_direct(registry):
    async def dummy_handler(args):
        return "ok"
        
    tool_def = ToolDefinition(
        name="direct_tool",
        description="direct tool description",
        input_schema={},
        handler=dummy_handler
    )
    registry.register_tool(tool_def)
    assert registry.get_tool("direct_tool") is tool_def

@pytest.mark.asyncio
async def test_execute_tool_not_found(registry):
    res = await registry.execute("non_existent", {})
    assert res.is_error is True
    assert "non_existent" in res.content[0]["text"]
    assert "\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093" in res.content[0]["text"]

@pytest.mark.asyncio
async def test_execute_scope_insufficient(registry):
    @registry.register(
        name="scoped_tool",
        description="scoped tool description",
        input_schema={},
        required_scopes={"admin"}
    )
    async def scoped_tool(args):
        return "ok"

    res = await registry.execute("scoped_tool", {}, caller_scopes=set())
    assert res.is_error is True
    assert "\u6a29\u9650\u4e0d\u8db3" in res.content[0]["text"]

@pytest.mark.asyncio
async def test_execute_validation_error(registry):
    @registry.register(
        name="val_tool",
        description="validation tool description",
        input_schema={"required_param": str}
    )
    async def val_tool(args):
        return "ok"

    res = await registry.execute("val_tool", {})
    assert res.is_error is True
    assert "\u5fc5\u9808\u5f15\u6570" in res.content[0]["text"]
    assert "required_param" in res.content[0]["text"]

@pytest.mark.asyncio
async def test_execute_handler_exception(registry):
    @registry.register(
        name="error_tool",
        description="error tool description",
        input_schema={}
    )
    async def error_tool(args):
        raise ValueError("intentional error")

    res = await registry.execute("error_tool", {})
    assert res.is_error is True
    assert "intentional error" in res.content[0]["text"]
    
    stats = registry.get_stats()
    assert stats["tools"]["error_tool"]["errors"] == 1

@pytest.mark.asyncio
async def test_sync_handler_execution(registry):
    @registry.register(
        name="sync_tool",
        description="sync tool description",
        input_schema={"x": int}
    )
    def sync_tool(args):
        return {"val": args["x"] + 1}

    res = await registry.execute("sync_tool", {"x": 10})
    assert res.is_error is False
    assert res.content[0]["text"] == '{"val": 11}'

@pytest.mark.asyncio
async def test_validate_args_optional_and_default(registry):
    @registry.register(
        name="opt_tool",
        description="optional tool description",
        input_schema={
            "opt_param": "Optional[str]", 
            "def_param": {"type": int, "default": 20}
        }
    )
    async def opt_tool(args):
        return "ok"

    res = await registry.execute("opt_tool", {})
    assert res.is_error is False

@pytest.mark.asyncio
async def test_validate_args_path_normalization(registry):
    @registry.register(
        name="path_tool",
        description="path tool description",
        input_schema={"video_path": str}
    )
    async def path_tool(args):
        return args["video_path"]

    res = await registry.execute("path_tool", {"video_path": "relative/path/to/video.mp4"})
    assert res.is_error is False
    normalized_path = res.content[0]["text"]
    assert Path(normalized_path).is_absolute()

@pytest.mark.asyncio
async def test_normalize_result_tool_result_instance(registry):
    expected_res = ToolResult(content=[{"type": "text", "text": "already tool result"}], is_error=False)
    
    @registry.register(
        name="res_tool",
        description="result tool description",
        input_schema={}
    )
    async def res_tool(args):
        return expected_res

    res = await registry.execute("res_tool", {})
    assert res is expected_res
    assert res.tool_name == "res_tool"

@pytest.mark.asyncio
async def test_normalize_result_various_patterns(registry):
    @registry.register(
        name="error_dict_tool",
        description="error dict tool description",
        input_schema={}
    )
    async def error_dict_tool(args):
        return {"status": "error", "message": "dict error"}

    res = await registry.execute("error_dict_tool", {})
    assert res.is_error is True
    assert "dict error" in res.content[0]["text"]

    @registry.register(
        name="content_dict_tool",
        description="content dict tool description",
        input_schema={}
    )
    async def content_dict_tool(args):
        return {"content": [{"type": "text", "text": "custom content"}], "is_error": True}

    res = await registry.execute("content_dict_tool", {})
    assert res.is_error is True
    assert res.content[0]["text"] == "custom content"

    @registry.register(
        name="json_err_tool",
        description="json error tool description",
        input_schema={}
    )
    async def json_err_tool(args):
        return '{"status": "error", "details": "something bad"}'

    res = await registry.execute("json_err_tool", {})
    assert res.is_error is True
    assert "something bad" in res.content[0]["text"]

    @registry.register(
        name="json_ok_tool",
        description="json success tool description",
        input_schema={}
    )
    async def json_ok_tool(args):
        return '{"status": "success", "details": "all good"}'

    res = await registry.execute("json_ok_tool", {})
    assert res.is_error is False
    assert "all good" in res.content[0]["text"]

    @registry.register(
        name="non_json_tool",
        description="non json tool description",
        input_schema={}
    )
    async def non_json_tool(args):
        return "just plain text"

    res = await registry.execute("non_json_tool", {})
    assert res.is_error is False
    assert res.content[0]["text"] == "just plain text"

    @registry.register(
        name="other_type_tool",
        description="other type tool description",
        input_schema={}
    )
    async def other_type_tool(args):
        return 42

    res = await registry.execute("other_type_tool", {})
    assert res.is_error is False
    assert res.content[0]["text"] == "42"

def test_get_tool_not_found(registry):
    assert registry.get_tool("missing_tool") is None

@pytest.mark.asyncio
async def test_get_stats(registry):
    @registry.register(
        name="stats_tool",
        description="stats tool description",
        input_schema={}
    )
    async def stats_tool(args):
        return "ok"

    await registry.execute("stats_tool", {})
    stats = registry.get_stats()
    assert stats["tool_count"] == 1
    assert "stats_tool" in stats["tools"]
    assert stats["tools"]["stats_tool"]["calls"] == 1

def test_list_tools_and_type_conversion(registry):
    @registry.register(
        name="schema_tool",
        description="schema tool description",
        input_schema={
            "my_str": str,
            "my_int": int,
            "my_float": float,
            "my_bool": bool,
            "my_list": list,
            "my_dict": dict,
            "my_custom": {"type": int, "default": 100},
            "my_unknown": object
        }
    )
    async def schema_tool(args):
        return "ok"

    tools = registry.list_tools()
    assert len(tools) == 1
    t = tools[0]
    assert t["name"] == "mcp__antigravity_pipeline__schema_tool"
    assert t["description"] == "schema tool description"
    
    properties = t["inputSchema"]["properties"]
    assert properties["my_str"]["type"] == "string"
    assert properties["my_int"]["type"] == "integer"
    assert properties["my_float"]["type"] == "number"
    assert properties["my_bool"]["type"] == "boolean"
    assert properties["my_list"]["type"] == "array"
    assert properties["my_dict"]["type"] == "object"
    assert properties["my_custom"]["type"] == "integer"
    assert properties["my_unknown"]["type"] == "string"
