import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from quality_gate_ai import AIQualityChecker, CustomRule, QualityHistory, ai_quality_checker


@pytest.mark.asyncio
async def test_model_name_resolution_fallback_registry():
    """ImportError fallback to model_registry"""
    mock_registry = MagicMock()
    mock_registry.get_model.return_value = "custom-registry-model"
    
    with patch.dict(sys.modules, {
        "model_governance": None,
        "model_registry": mock_registry
    }):
        checker = AIQualityChecker()
        assert checker._model_name == "custom-registry-model"
        mock_registry.get_model.assert_called_once_with("quality_gate")


@pytest.mark.asyncio
async def test_model_name_resolution_fallback_default():
    """ImportError fallback to gemini-3.6-flash when all fail"""
    with patch.dict(sys.modules, {
        "model_governance": None,
        "model_registry": None
    }):
        checker = AIQualityChecker()
        assert checker._model_name == "gemini-3.6-flash"


@pytest.mark.asyncio
async def test_check_context_coherence_success():
    """check_context_coherence method success path"""
    mock_gov_module = MagicMock()
    mock_model_governance = MagicMock()
    mock_model_governance.call = AsyncMock(return_value="Coherence test passed")
    mock_gov_module.model_governance = mock_model_governance
    
    with patch.dict(sys.modules, {"model_governance": mock_gov_module}):
        checker = AIQualityChecker()
        result = await checker.check_context_coherence(
            scenes=[{"id": 1, "description": "test scene"}],
            subtitles=["Hello test"]
        )
        assert result == {"status": "success", "result": "Coherence test passed"}
        mock_model_governance.call.assert_called_once()


@pytest.mark.asyncio
async def test_check_context_coherence_value_error():
    """check_context_coherence method raises ValueError"""
    mock_gov_module = MagicMock()
    mock_model_governance = MagicMock()
    mock_model_governance.call = AsyncMock(side_effect=ValueError("API key not set"))
    mock_gov_module.model_governance = mock_model_governance
    
    with patch.dict(sys.modules, {"model_governance": mock_gov_module}):
        checker = AIQualityChecker()
        result = await checker.check_context_coherence(
            scenes=[{"id": 1, "description": "test scene"}],
            subtitles=["Hello test"]
        )
        assert result == {"status": "skipped", "reason": "API key not set"}


@pytest.mark.asyncio
async def test_check_context_coherence_general_exception():
    """check_context_coherence method raises generic Exception"""
    mock_gov_module = MagicMock()
    mock_model_governance = MagicMock()
    mock_model_governance.call = AsyncMock(side_effect=RuntimeError("Connection failed"))
    mock_gov_module.model_governance = mock_model_governance
    
    with patch.dict(sys.modules, {"model_governance": mock_gov_module}):
        checker = AIQualityChecker()
        result = await checker.check_context_coherence(
            scenes=[{"id": 1, "description": "test scene"}],
            subtitles=["Hello test"]
        )
        assert result == {"status": "error", "error": "Connection failed"}

@pytest.mark.asyncio
async def test_check_context_coherence_type_error():
    """check_context_coherence method handles TypeError"""
    mock_gov_module = MagicMock()
    mock_model_governance = MagicMock()
    mock_model_governance.call = AsyncMock(side_effect=TypeError("Invalid type argument"))
    mock_gov_module.model_governance = mock_model_governance
    
    with patch.dict(sys.modules, {"model_governance": mock_gov_module}):
        checker = AIQualityChecker()
        result = await checker.check_context_coherence(
            scenes=[{"id": 1, "description": "test scene"}],
            subtitles=["Hello test"]
        )
        assert result == {"status": "error", "error": "Invalid type argument"}


@pytest.mark.asyncio
async def test_check_context_coherence_import_error():
    """check_context_coherence method handles ImportError"""
    mock_gov_module = MagicMock()
    mock_model_governance = MagicMock()
    mock_model_governance.call = AsyncMock(side_effect=ImportError("Failed to import module"))
    mock_gov_module.model_governance = mock_model_governance
    
    with patch.dict(sys.modules, {"model_governance": mock_gov_module}):
        checker = AIQualityChecker()
        result = await checker.check_context_coherence(
            scenes=[{"id": 1, "description": "test scene"}],
            subtitles=["Hello test"]
        )
        assert result == {"status": "error", "error": "Failed to import module"}


@pytest.mark.asyncio
async def test_check_context_coherence_unhandled_exception():
    """check_context_coherence method does not handle KeyError (propagates up)"""
    mock_gov_module = MagicMock()
    mock_model_governance = MagicMock()
    mock_model_governance.call = AsyncMock(side_effect=KeyError("Missing key"))
    mock_gov_module.model_governance = mock_model_governance
    
    with patch.dict(sys.modules, {"model_governance": mock_gov_module}):
        checker = AIQualityChecker()
        with pytest.raises(KeyError):
            await checker.check_context_coherence(
                scenes=[{"id": 1, "description": "test scene"}],
                subtitles=["Hello test"]
            )


@pytest.mark.asyncio
async def test_check_custom_rules_keyword_and_regex():
    """check_custom_rules matching with keywords and regex, including disabled rules"""
    checker = AIQualityChecker()
    # Add rules manually to not pollute the global singleton
    rule_kw = CustomRule(
        id="test_kw",
        name="Test Keyword",
        description="Found keyword",
        check_type="keyword",
        pattern="testkey",
        severity="warning",
        enabled=True
    )
    rule_rx = CustomRule(
        id="test_rx",
        name="Test Regex",
        description="Found regex",
        check_type="regex",
        pattern=r"rx\d+",
        severity="error",
        enabled=True
    )
    rule_disabled = CustomRule(
        id="test_disabled",
        name="Disabled Rule",
        description="Should not trigger",
        check_type="keyword",
        pattern="disabled",
        severity="info",
        enabled=False
    )
    
    checker.add_custom_rule(rule_kw)
    checker.add_custom_rule(rule_rx)
    checker.add_custom_rule(rule_disabled)
    
    # Test text triggering keyword and regex
    issues = checker.check_custom_rules("This is a testkey and rx123 but also disabled")
    assert len(issues) == 2
    
    ids = [issue["rule_id"] for issue in issues]
    assert "test_kw" in ids
    assert "test_rx" in ids
    assert "test_disabled" not in ids


def test_quality_history_and_issue_prediction():
    """record_issue, get_common_issues, and predict_issues"""
    checker = AIQualityChecker()
    
    # Empty history
    assert checker.get_common_issues() == []
    assert checker.predict_issues("test") == []
    
    # Record some issues
    checker.record_issue(QualityHistory(issue_type="A", message="msg A", timestamp="2026-05-26"))
    checker.record_issue(QualityHistory(issue_type="A", message="msg A2", timestamp="2026-05-26"))
    checker.record_issue(QualityHistory(issue_type="B", message="msg B", timestamp="2026-05-26"))
    
    common = checker.get_common_issues(limit=1)
    assert len(common) == 1
    assert common[0] == {"type": "A", "count": 2}
    
    # predictions should be empty because no issue has count >= 3
    assert checker.predict_issues("test") == []
    
    # Add one more "A" to make count >= 3
    checker.record_issue(QualityHistory(issue_type="A", message="msg A3", timestamp="2026-05-26"))
    predictions = checker.predict_issues("test")
    assert len(predictions) == 1
    assert "過去に'A'の問題が3回発生しています" in predictions[0]




def test_build_coherence_prompt():
    """_build_coherence_prompt builds expected prompt string"""
    checker = AIQualityChecker()
    scenes = [{"id": 1, "description": "Scene A"}]
    subtitles = ["Subtitle A"]
    prompt = checker._build_coherence_prompt(scenes, subtitles)
    assert "Scene A" in prompt
    assert "Subtitle A" in prompt
    assert "シーン情報:" in prompt
    assert "字幕サンプル:" in prompt


def test_check_custom_rules_unsupported_type():
    """check_custom_rules with unsupported check_type evaluates to False and skips"""
    checker = AIQualityChecker()
    rule_kw = CustomRule(
        id="test_kw",
        name="Test Keyword",
        description="Found keyword",
        check_type="keyword",
        pattern="testkey",
        severity="warning",
        enabled=True
    )
    rule_unsupported = CustomRule(
        id="test_unsupported",
        name="Unsupported Type",
        description="Should not trigger",
        check_type="ai",  # Unsupported check_type
        pattern="unused_pattern",
        severity="info",
        enabled=True
    )
    
    checker.add_custom_rule(rule_kw)
    checker.add_custom_rule(rule_unsupported)
    
    # Test text that triggers keyword but should skip the unsupported rule
    issues = checker.check_custom_rules("This is a testkey")
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "test_kw"
