import pytest
from unittest.mock import MagicMock, patch
from services.prediction_validator import prediction_validator, PredictionValidator

@pytest.mark.asyncio
async def test_validate_prediction_no_manager():
    # 1. wagamama_manager is None
    result = await prediction_validator.validate_prediction("wagamama_123", {}, wagamama_manager=None)
    assert result == {"status": "error", "message": "Manager not provided"}

@pytest.mark.asyncio
async def test_validate_prediction_no_record():
    # 2. Record not found
    mock_manager = MagicMock()
    mock_manager.get_record.return_value = None
    
    result = await prediction_validator.validate_prediction("wagamama_123", {}, wagamama_manager=mock_manager)
    assert result == {"status": "error", "message": "No record found for validation"}
    mock_manager.get_record.assert_called_once_with("wagamama_123")

@pytest.mark.asyncio
async def test_validate_prediction_no_predicted_ctr():
    # 3. predicted_ctr is None
    mock_manager = MagicMock()
    # Case A: empty experience lane
    mock_manager.get_record.return_value = {
        "lanes": {
            "experience": {}
        }
    }
    result = await prediction_validator.validate_prediction("wagamama_123", {}, wagamama_manager=mock_manager)
    assert result == {"status": "skipped", "message": "No predicted CTR available for comparison"}

    # Case B: no experience lane
    mock_manager.get_record.return_value = {
        "lanes": {}
    }
    result = await prediction_validator.validate_prediction("wagamama_123", {}, wagamama_manager=mock_manager)
    assert result == {"status": "skipped", "message": "No predicted CTR available for comparison"}

@pytest.mark.asyncio
async def test_validate_prediction_success_within_variance():
    # 4. Success, within normal variance
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    actual_metrics = {
        "metrics": {
            "click_through_rate": 0.055
        },
        "elapsed_hours": 48
    }
    
    result = await prediction_validator.validate_prediction("wagamama_123", actual_metrics, wagamama_manager=mock_manager)
    
    assert result["wagamama_id"] == "wagamama_123"
    assert result["prediction"]["ctr"] == 0.05
    assert result["actual"]["ctr"] == 0.055
    assert result["actual"]["elapsed_hours"] == 48
    assert result["analysis"]["difference"] == 0.00  # 0.055 - 0.05 = 0.005 -> round(0.005, 2) is 0.0 in Python (bankers rounding)
    assert result["analysis"]["significant_deviation"] is False
    
    # Check that feedback lane was updated in record
    assert "feedback" in record["lanes"]
    assert record["lanes"]["feedback"]["validation_report"] == result
    
    # Check that save was called
    mock_manager._save.assert_called_once()

@pytest.mark.asyncio
async def test_validate_prediction_significant_deviation():
    # 5. Significant deviation
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    actual_metrics = {
        "metrics": {
            "click_through_rate": 0.08
        }
    }
    
    result = await prediction_validator.validate_prediction("wagamama_123", actual_metrics, wagamama_manager=mock_manager)
    
    assert result["analysis"]["difference"] == 0.03
    assert result["analysis"]["error_margin_pct"] == 60.0
    assert result["analysis"]["significant_deviation"] is True
    assert result["actual"]["elapsed_hours"] == 24  # default

@pytest.mark.asyncio
async def test_validate_prediction_zero_ctr():
    # 6. predicted_ctr is 0
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.0
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    result = await prediction_validator.validate_prediction("wagamama_123", None, wagamama_manager=mock_manager)
    assert result["prediction"]["ctr"] == 0.0
    assert result["actual"]["ctr"] == 0.0
    assert result["analysis"]["error_margin_pct"] == 0.0
    assert result["analysis"]["significant_deviation"] is False

@pytest.mark.asyncio
async def test_validate_prediction_missing_metrics_key():
    # 7. actual_metrics contains no "metrics" key
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    actual_metrics = {
        "elapsed_hours": 30
    }
    
    result = await prediction_validator.validate_prediction("wagamama_123", actual_metrics, wagamama_manager=mock_manager)
    assert result["actual"]["ctr"] == 0.0
    assert result["actual"]["elapsed_hours"] == 30
    assert result["analysis"]["significant_deviation"] is True  # 0.05 vs 0.0 -> error margin is 100.0% > 30%

@pytest.mark.asyncio
async def test_validate_prediction_missing_ctr_key():
    # 8. metrics key exists but click_through_rate key is missing
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    actual_metrics = {
        "metrics": {}
    }
    
    result = await prediction_validator.validate_prediction("wagamama_123", actual_metrics, wagamama_manager=mock_manager)
    assert result["actual"]["ctr"] == 0.0
    assert result["analysis"]["significant_deviation"] is True

@pytest.mark.asyncio
async def test_validate_prediction_negative_predicted_ctr():
    # 9. predicted_ctr is negative (abnormal value)
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": -0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    result = await prediction_validator.validate_prediction("wagamama_123", None, wagamama_manager=mock_manager)
    assert result["prediction"]["ctr"] == -0.05
    assert result["actual"]["ctr"] == 0.0
    # error_margin should be 0 because predicted_ctr <= 0
    assert result["analysis"]["error_margin_pct"] == 0.0
    assert result["analysis"]["significant_deviation"] is False

@pytest.mark.asyncio
async def test_validate_prediction_boundary_deviation():
    # 10. Boundary conditions for significant_deviation (threshold 30%)
    mock_manager = MagicMock()
    
    # Case A: exactly 30% deviation (error_margin = 0.3)
    # predicted = 0.10, actual = 0.13 -> deviation = (0.13 - 0.10) / 0.10 = 0.3
    record_a = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.10
            }
        }
    }
    mock_manager.get_record.return_value = record_a
    actual_metrics_a = {"metrics": {"click_through_rate": 0.13}}
    result_a = await prediction_validator.validate_prediction("wagamama_123", actual_metrics_a, wagamama_manager=mock_manager)
    assert result_a["analysis"]["error_margin_pct"] == 30.0
    assert result_a["analysis"]["significant_deviation"] is False
    
    # Case B: slightly above 30% deviation (error_margin > 0.3)
    # predicted = 0.10, actual = 0.1301 -> deviation = (0.1301 - 0.10) / 0.10 = 0.301 > 0.3
    record_b = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.10
            }
        }
    }
    mock_manager.get_record.return_value = record_b
    actual_metrics_b = {"metrics": {"click_through_rate": 0.1301}}
    result_b = await prediction_validator.validate_prediction("wagamama_123", actual_metrics_b, wagamama_manager=mock_manager)
    assert result_b["analysis"]["error_margin_pct"] == 30.10
    assert result_b["analysis"]["significant_deviation"] is True


@pytest.mark.asyncio
async def test_validate_prediction_invalid_lanes_type():
    # 11. Record contains non-dict type for lanes
    mock_manager = MagicMock()
    record = {
        "lanes": "not_a_dict"
    }
    mock_manager.get_record.return_value = record
    
    with pytest.raises(AttributeError):
        await prediction_validator.validate_prediction("wagamama_123", {}, wagamama_manager=mock_manager)

@pytest.mark.asyncio
async def test_validate_prediction_logging(caplog):
    # 12. Verify logger message outputs for normal vs significant deviation
    import logging
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    # Case A: Within normal variance log check
    actual_metrics_normal = {"metrics": {"click_through_rate": 0.055}}
    with caplog.at_level(logging.INFO):
        await prediction_validator.validate_prediction("wagamama_123", actual_metrics_normal, wagamama_manager=mock_manager)
    assert any("Within normal variance" in message for message in caplog.messages)
    
    caplog.clear()
    
    # Case B: Significant deviation log check
    actual_metrics_deviation = {"metrics": {"click_through_rate": 0.08}}
    with caplog.at_level(logging.INFO):
        await prediction_validator.validate_prediction("wagamama_123", actual_metrics_deviation, wagamama_manager=mock_manager)
    assert any("Significant deviation" in message for message in caplog.messages)

@pytest.mark.asyncio
async def test_validate_prediction_fixed_time():
    # 13. Verify datetime generation using mocking
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    fixed_time_str = "2026-06-04T12:00:00.000000"
    with patch("services.prediction_validator.datetime") as mock_datetime:
        mock_datetime.now.return_value.isoformat.return_value = fixed_time_str
        
        result = await prediction_validator.validate_prediction("wagamama_123", {}, wagamama_manager=mock_manager)
        assert result["validated_at"] == fixed_time_str

@pytest.mark.asyncio
async def test_validate_prediction_new_instance():
    # 14. Verify creation and execution of a non-singleton instance of PredictionValidator
    validator = PredictionValidator()
    mock_manager = MagicMock()
    record = {
        "lanes": {
            "experience": {
                "predicted_ctr": 0.05
            }
        }
    }
    mock_manager.get_record.return_value = record
    
    result = await validator.validate_prediction("wagamama_123", {}, wagamama_manager=mock_manager)
    assert result.get("status") != "error"
    assert result["wagamama_id"] == "wagamama_123"
