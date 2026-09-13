"""
test_adk_agent_template.py — adk_agent_template.py のユニットテスト

目的:
- agents/adk_agent_template.py のテストカバレッジ 100% を維持・達成する。
"""

import sys
import importlib
import logging
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# backend を sys.path に追加
backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def test_module_load_with_model_registry():
    """model_registry が存在する場合に DEFAULT_MODEL が正常に初期化されること"""
    # 一旦 agents.adk_agent_template を sys.modules から削除して再ロードさせる
    sys.modules.pop("agents.adk_agent_template", None)

    mock_get_model = MagicMock(return_value="gemini-mock-supervisor")
    with patch.dict("sys.modules", {"model_registry": MagicMock(get_model=mock_get_model)}):
        import agents.adk_agent_template
        # ロード時点で DEFAULT_MODEL が mock_get_model() に解決されているはず
        assert agents.adk_agent_template.DEFAULT_MODEL == "gemini-mock-supervisor"
        mock_get_model.assert_called_once_with("supervisor")


def test_module_load_without_model_registry():
    """model_registry が存在しない（ImportError）場合に DEFAULT_MODEL がフォールバックされること"""
    sys.modules.pop("agents.adk_agent_template", None)

    with patch.dict("sys.modules", {"model_registry": None}):
        import agents.adk_agent_template
        assert agents.adk_agent_template.DEFAULT_MODEL == "gemini-3.6-flash"


def test_resolve_model_from_registry_with_registry():
    """_resolve_model_from_registry が model_registry からモデルを取得すること"""
    sys.modules.pop("agents.adk_agent_template", None)
    mock_get_model = MagicMock(return_value="gemini-mock-task")

    with patch.dict("sys.modules", {"model_registry": MagicMock(get_model=mock_get_model)}):
        import agents.adk_agent_template
        model = agents.adk_agent_template._resolve_model_from_registry("custom_task")
        assert model == "gemini-mock-task"
        mock_get_model.assert_called_with("custom_task")


def test_resolve_model_from_registry_without_registry():
    """_resolve_model_from_registry で model_registry が存在しない場合に DEFAULT_MODEL が返されること"""
    sys.modules.pop("agents.adk_agent_template", None)

    with patch.dict("sys.modules", {"model_registry": None}):
        import agents.adk_agent_template
        model = agents.adk_agent_template._resolve_model_from_registry("custom_task")
        assert model == "gemini-3.6-flash"


def test_create_agent_import_error():
    """google-adk がインストールされていない場合、ImportError が発生しログが出力されること"""
    import agents.adk_agent_template
    
    with patch.dict("sys.modules", {"google.adk.agents": None}):
        with patch.object(agents.adk_agent_template.logger, "error") as mock_log_error:
            with pytest.raises(ImportError):
                agents.adk_agent_template.create_agent(
                    name="test_agent",
                    instruction="You are a helpful assistant"
                )
            mock_log_error.assert_called_once()
            assert "google-adk パッケージがインストールされていません" in mock_log_error.call_args[0][0]


def test_create_agent_success():
    """create_agent が ADK Agent インスタンスを正常に生成すること（各種オプション付き）"""
    import agents.adk_agent_template

    mock_agent_class = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_class.return_value = mock_agent_instance

    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        with patch("agents.adk_agent_template._resolve_model_from_registry", return_value="gemini-mock-default"):
            # 1. 最小構成での生成
            agent = agents.adk_agent_template.create_agent(
                name="min_agent",
                instruction="Simple instruction"
            )
            assert agent == mock_agent_instance
            mock_agent_class.assert_called_with(
                name="min_agent",
                model="gemini-mock-default",
                instruction="Simple instruction",
                description="min_agent agent"
            )

            # 2. フル構成での生成
            mock_tool1 = lambda x: x
            mock_tool2 = lambda y: y
            sub_agent = MagicMock()

            agent_full = agents.adk_agent_template.create_agent(
                name="full_agent",
                instruction="Detailed instruction",
                tools=[mock_tool1, mock_tool2],
                model="gemini-large",
                description="A premium agent",
                sub_agents=[sub_agent],
                output_key="dashboard_status"
            )
            assert agent_full == mock_agent_instance
            mock_agent_class.assert_called_with(
                name="full_agent",
                model="gemini-large",
                instruction="Detailed instruction",
                description="A premium agent",
                tools=[mock_tool1, mock_tool2],
                sub_agents=[sub_agent],
                output_key="dashboard_status"
            )


def test_create_council_agent():
    """create_council_agent が指定された役割と専門分野に基づいて正しくエージェントを作成すること"""
    import agents.adk_agent_template

    mock_agent_class = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_class.return_value = mock_agent_instance

    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        agent = agents.adk_agent_template.create_council_agent(
            name="analyst_agent",
            role="Analyst",
            expertise="Video Analytics & Trend Tracking",
            model="gemini-1.5-pro"
        )
        assert agent == mock_agent_instance

        # 呼び出しパラメータの検証
        args, kwargs = mock_agent_class.call_args
        assert kwargs["name"] == "analyst_agent"
        assert kwargs["model"] == "gemini-1.5-pro"
        assert kwargs["description"] == "Council of Minds - Analyst: Video Analytics & Trend Tracking"
        assert "あなたは「Council of Minds（議会）」のAnalystです。" in kwargs["instruction"]
        assert "Video Analytics & Trend Tracking" in kwargs["instruction"]


def test_tool_decorator():
    """@tool デコレータが正しく関数に _is_adk_tool 属性を付与すること"""
    import agents.adk_agent_template

    @agents.adk_agent_template.tool
    def my_custom_tool(arg1: str) -> bool:
        """My tool description."""
        return True

    assert hasattr(my_custom_tool, "_is_adk_tool")
    assert my_custom_tool._is_adk_tool is True


def test_create_council_agent_with_tools():
    """create_council_agent に tools を渡した際に Agent に正しく設定されること"""
    import agents.adk_agent_template

    mock_agent_class = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_class.return_value = mock_agent_instance

    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        mock_tool = lambda: None
        agent = agents.adk_agent_template.create_council_agent(
            name="writer_agent",
            role="Writer",
            expertise="Script writing & Editing",
            tools=[mock_tool],
            model="gemini-1.5-flash"
        )
        assert agent == mock_agent_instance

        # 呼び出しパラメータの検証
        args, kwargs = mock_agent_class.call_args
        assert kwargs["name"] == "writer_agent"
        assert kwargs["model"] == "gemini-1.5-flash"
        assert kwargs["tools"] == [mock_tool]


def test_tool_decorator_edge_cases():
    """@tool デコレータが様々な形式の関数（引数なしなど）に適用可能なこと"""
    import agents.adk_agent_template

    # 1. 引数なしの関数
    @agents.adk_agent_template.tool
    def simple_no_args_tool():
        return "ok"

    assert hasattr(simple_no_args_tool, "_is_adk_tool")
    assert simple_no_args_tool._is_adk_tool is True

    # 2. 型ヒントなしの関数
    @agents.adk_agent_template.tool
    def no_type_hints_tool(a, b):
        return a + b

    assert hasattr(no_type_hints_tool, "_is_adk_tool")
    assert no_type_hints_tool._is_adk_tool is True


def test_create_agent_edge_cases():
    """create_agent の引数の境界値やデフォルトフォールバックを検証する"""
    import agents.adk_agent_template
    from unittest.mock import MagicMock, patch

    mock_agent_class = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_class.return_value = mock_agent_instance

    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        # 1. tools と sub_agents に空リスト [] を渡した場合、または None の場合
        
        # 1.1 tools=[], sub_agents=None, output_key=None, description=""
        agent1 = agents.adk_agent_template.create_agent(
            name="agent_empty_lists",
            instruction="instruction",
            tools=[],
            sub_agents=None,
            output_key=None,
            description=""
        )
        mock_agent_class.assert_called_with(
            name="agent_empty_lists",
            model=agents.adk_agent_template._resolve_model_from_registry(),
            instruction="instruction",
            description="agent_empty_lists agent"
        )

        # 1.2 tools=None, sub_agents=[]
        agent2 = agents.adk_agent_template.create_agent(
            name="agent_empty_subagents",
            instruction="instruction",
            tools=None,
            sub_agents=[]
        )
        mock_agent_class.assert_called_with(
            name="agent_empty_subagents",
            model=agents.adk_agent_template._resolve_model_from_registry(),
            instruction="instruction",
            description="agent_empty_subagents agent"
        )


def test_create_agent_with_explicit_model_skips_registry():
    """model が明示的に指定された場合、_resolve_model_from_registry が呼ばれないこと"""
    import agents.adk_agent_template
    from unittest.mock import MagicMock, patch

    mock_agent_class = MagicMock()
    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        with patch("agents.adk_agent_template._resolve_model_from_registry") as mock_get_default:
            agents.adk_agent_template.create_agent(
                name="explicit_model_agent",
                instruction="instruction",
                model="gemini-explicit-model"
            )
            mock_get_default.assert_not_called()
            mock_agent_class.assert_called_with(
                name="explicit_model_agent",
                model="gemini-explicit-model",
                instruction="instruction",
                description="explicit_model_agent agent"
            )


def test_create_council_agent_edge_cases():
    """create_council_agent の引数の境界値を検証する"""
    import agents.adk_agent_template
    from unittest.mock import MagicMock, patch

    mock_agent_class = MagicMock()
    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        agents.adk_agent_template.create_council_agent(
            name="council_edge",
            role="Expert",
            expertise="Deep knowledge",
            tools=None,
            model=None
        )
        args, kwargs = mock_agent_class.call_args
        assert kwargs["model"] == agents.adk_agent_template._resolve_model_from_registry()
        assert "tools" not in kwargs


def test_tool_decorator_on_methods():
    """@tool デコレータをクラスメソッド等に適用した際の挙動"""
    import agents.adk_agent_template

    class MyService:
        @agents.adk_agent_template.tool
        def process_data(self, data: str) -> str:
            return data.upper()

        @classmethod
        @agents.adk_agent_template.tool
        def class_tool(cls):
            return "class_ok"

    service = MyService()
    assert hasattr(service.process_data, "_is_adk_tool")
    assert service.process_data._is_adk_tool is True

    assert hasattr(MyService.class_tool, "_is_adk_tool")
    assert MyService.class_tool._is_adk_tool is True


def test_module_load_with_registry_exception():
    """model_registry は存在するが get_model が例外をスローする場合、DEFAULT_MODEL が正常にフォールバックされること"""
    sys.modules.pop("agents.adk_agent_template", None)

    mock_get_model = MagicMock(side_effect=RuntimeError("Registry failed during import"))
    with patch.dict("sys.modules", {"model_registry": MagicMock(get_model=mock_get_model)}):
        import agents.adk_agent_template
        assert agents.adk_agent_template.DEFAULT_MODEL == "gemini-3.6-flash"


def test_resolve_model_from_registry_with_exception():
    """_resolve_model_from_registry 内で例外が発生した場合に DEFAULT_MODEL にフォールバックされること"""
    sys.modules.pop("agents.adk_agent_template", None)

    # 1回目はロード時 (DEFAULT_MODEL = get_model("supervisor")) で成功させ、2回目の custom_task で例外をスローさせる
    mock_get_model = MagicMock(side_effect=["gemini-mock-default", RuntimeError("Registry error during task resolution")])
    with patch.dict("sys.modules", {"model_registry": MagicMock(get_model=mock_get_model)}):
        import agents.adk_agent_template
        assert agents.adk_agent_template.DEFAULT_MODEL == "gemini-mock-default"
        
        model = agents.adk_agent_template._resolve_model_from_registry("custom_task")
        assert model == "gemini-mock-default"


def test_create_agent_exception():
    """例外が発生した場合、create_agent が例外をキャッチして None を返し、ログを出力すること"""
    import agents.adk_agent_template

    with patch("agents.adk_agent_template._verify_adk_installed", side_effect=RuntimeError("ADK check crashed")):
        with patch.object(agents.adk_agent_template.logger, "exception") as mock_log_exception:
            agent = agents.adk_agent_template.create_agent(
                name="crashed_agent",
                instruction="You are a normal agent"
            )
            assert agent is None
            mock_log_exception.assert_called_once()
            assert "Failed to create agent 'crashed_agent'" in mock_log_exception.call_args[0][0]


def test_execute_agent_run_success():
    """execute_agent_run がエージェントの実行に成功し、(True, result) を返すこと"""
    import agents.adk_agent_template

    mock_agent = MagicMock()
    mock_agent.run.return_value = "Run response"

    success, result = agents.adk_agent_template.execute_agent_run(mock_agent, "my query")
    assert success is True
    assert result == "Run response"
    mock_agent.run.assert_called_once_with("my query")


def test_execute_agent_run_exception():
    """execute_agent_run 中に例外が発生した場合、例外をキャッチして (False, None) を返し、ログを出力すること"""
    import agents.adk_agent_template

    mock_agent = MagicMock()
    mock_agent.run.side_effect = RuntimeError("Execution crash")

    with patch.object(agents.adk_agent_template.logger, "exception") as mock_log_exception:
        success, result = agents.adk_agent_template.execute_agent_run(mock_agent, "my query")
        assert success is False
        assert result is None
        mock_log_exception.assert_called_once()
        assert "Agent execution failed" in mock_log_exception.call_args[0][0]


def test_create_agent_invalid_types_and_none():
    """create_agent に None や不正な型を渡した場合の挙動を検証する"""
    import agents.adk_agent_template

    mock_agent_class = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_class.return_value = mock_agent_instance

    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        # 1. 引数が None の場合
        # 通常、型ヒントで制限されているが Python 自体は実行できるため、そのまま Agent に渡されるはず
        agent_none = agents.adk_agent_template.create_agent(
            name=None,
            instruction=None,
            tools=None,
            model=None
        )
        assert agent_none == mock_agent_instance
        mock_agent_class.assert_called_with(
            name=None,
            model=agents.adk_agent_template._resolve_model_from_registry(),
            instruction=None,
            description="None agent"
        )

        # 2. 巨大な文字列の入力
        huge_name = "A" * 1000
        huge_instruction = "B" * 10000
        agent_huge = agents.adk_agent_template.create_agent(
            name=huge_name,
            instruction=huge_instruction
        )
        assert agent_huge == mock_agent_instance
        mock_agent_class.assert_called_with(
            name=huge_name,
            model=agents.adk_agent_template._resolve_model_from_registry(),
            instruction=huge_instruction,
            description=f"{huge_name} agent"
        )


def test_execute_agent_run_edge_cases():
    """execute_agent_run に None エージェントや異常なクエリを渡した場合"""
    import agents.adk_agent_template

    # 1. agent が None の場合 -> AttributeError が発生し、正常に False, None が返ること
    with patch.object(agents.adk_agent_template.logger, "exception") as mock_log_exception:
        success, result = agents.adk_agent_template.execute_agent_run(None, "query")
        assert success is False
        assert result is None
        mock_log_exception.assert_called_once()
        assert "Agent execution failed" in mock_log_exception.call_args[0][0]

    # 2. 空クエリ ""
    mock_agent = MagicMock()
    mock_agent.run.return_value = ""
    success, result = agents.adk_agent_template.execute_agent_run(mock_agent, "")
    assert success is True
    assert result == ""
    mock_agent.run.assert_called_once_with("")

    # 3. 巨大クエリ
    huge_query = "x" * 50000
    mock_agent_huge = MagicMock()
    mock_agent_huge.run.return_value = "processed huge query"
    success, result = agents.adk_agent_template.execute_agent_run(mock_agent_huge, huge_query)
    assert success is True
    assert result == "processed huge query"
    mock_agent_huge.run.assert_called_once_with(huge_query)


def test_create_council_agent_extreme_edge_cases():
    """create_council_agent に None や空文字を渡した場合"""
    import agents.adk_agent_template

    mock_agent_class = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_class.return_value = mock_agent_instance

    with patch.dict("sys.modules", {"google.adk.agents": MagicMock(Agent=mock_agent_class)}):
        # すべての引数を None や空にしてみる
        agent = agents.adk_agent_template.create_council_agent(
            name="",
            role="",
            expertise="",
            tools=None,
            model=None
        )
        assert agent == mock_agent_instance
        args, kwargs = mock_agent_class.call_args
        assert kwargs["name"] == ""
        assert kwargs["description"] == "Council of Minds - : "
        assert "あなたは「Council of Minds（議会）」のです。" in kwargs["instruction"]



