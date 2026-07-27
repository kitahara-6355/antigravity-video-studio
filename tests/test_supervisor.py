import sys
import warnings
import pytest
import logging

def test_deprecation_warning_on_import():
    if "backend.agents.supervisor" in sys.modules:
        del sys.modules["backend.agents.supervisor"]
    
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import backend.agents.supervisor
        
        assert len(w) >= 1
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        expected_msg = "agents.supervisor は非推奨です"
        assert expected_msg in str(deprecation_warnings[0].message)

def test_supervisor_agent_logging(caplog):
    import backend.agents.supervisor as supervisor
    
    with caplog.at_level(logging.WARNING):
        agent = supervisor.SupervisorAgent()
        
        assert len(caplog.records) >= 1
        warning_logs = [r for r in caplog.records if r.levelname == "WARNING"]
        expected_log = "SupervisorAgent は非推奨です"
        assert any(expected_log in r.message for r in warning_logs)

def test_supervisor_agent_route():
    import backend.agents.supervisor as supervisor
    agent = supervisor.SupervisorAgent()
    
    res = agent.route([])
    assert res.next == "FINISH"
    expected_reason = "SupervisorAgent は非推奨です"
    assert expected_reason in res.reason
    
    res_none = agent.route(None)
    assert res_none.next == "FINISH"
    
    res_invalid_type = agent.route("invalid_type")
    assert res_invalid_type.next == "FINISH"
    
    res_list_of_invalid = agent.route([1, 2, 3, {"key": "val"}])
    assert res_list_of_invalid.next == "FINISH"


def test_supervisor_agent_route_model_validation():
    import backend.agents.supervisor as supervisor
    from pydantic import ValidationError, BaseModel
    import pytest
    
    agent = supervisor.SupervisorAgent()
    res = agent.route([])
    
    # 戻り値が pydantic.BaseModel であることを確認
    assert isinstance(res, BaseModel)
    
    # クラス定義を取得してバリデーションチェック
    RouteClass = res.__class__
    
    # 正常な値での初期化
    valid_route = RouteClass(next="Analyst", reason="test")
    assert valid_route.next == "Analyst"
    assert valid_route.reason == "test"
    
    # 許容される Literal 値: "Analyst", "Strategist", "Director", "FINISH"
    for opt in ["Analyst", "Strategist", "Director", "FINISH"]:
        obj = RouteClass(next=opt, reason="ok")
        assert obj.next == opt
        
    # 許容されない next 値に対するバリデーションエラー
    with pytest.raises(ValidationError):
        RouteClass(next="InvalidAgent", reason="fail")
        
    # reason フィールドが欠落している場合
    with pytest.raises(ValidationError):
        RouteClass(next="FINISH")

def test_deprecation_warning_stacklevel():
    import sys
    import warnings
    import pytest
    
    # モジュールをアンロード
    if "backend.agents.supervisor" in sys.modules:
        del sys.modules["backend.agents.supervisor"]
        
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # インポートする。これが警告の呼び出し元になるため、
        # stacklevel=2 により警告発生元はこのテストファイル（__file__）と判定されるべきである。
        import backend.agents.supervisor
        
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        warning = deprecation_warnings[0]
        
        # 警告の発生元ファイルが本テストファイル（__file__）であることを検証
        assert warning.filename == __file__
