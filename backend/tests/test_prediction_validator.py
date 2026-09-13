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
    # **測っていない経過時間を既定値で埋めない**（R1.5-C4・19周目）。
    # ここは `== 24` を期待していたが、その 24 は「経過時間を一度も計測していないのに
    # 『公開から24時間後の実績』と名乗る」という捏造そのものだった。
    # この actual_metrics には elapsed_hours が無いので、いまは None が返る。
    assert result["actual"]["elapsed_hours"] is None
    # CTR のほうは実測が届いているので、印は measured のまま（本物なのは ctr だけ）
    assert result["actual"]["ctr"] == 0.08
    assert result["actual"]["is_real"] is True
    assert result["actual"]["data_source"] == "measured"

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
    # **届いていない実測を 0.0 で埋めない**（R1.5-C4・19周目）。
    # ここは `== 0.0` を期待していたが、その 0.0 は「実測が1つも来ていないのに
    # 『CTR 0% という実績が出た』と名乗る」という捏造そのものだった。
    # actual_metrics が None なので、いまは None が返り、印が unavailable になる。
    assert result["actual"]["ctr"] is None
    assert result["actual"]["is_real"] is False
    assert result["actual"]["data_source"] == "unavailable"
    # 誤差率も「0% ズレていた＝予測が当たった」ではなく「評価していない」が正直な値。
    assert result["analysis"]["checked"] is False
    assert result["analysis"]["error_margin_pct"] is None
    assert result["analysis"]["significant_deviation"] is None
    # 計測していない結果は台帳（Wagamama Ledger）へ焼き付けない
    assert result["status"] == "skipped"
    mock_manager._save.assert_not_called()

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
    # **届いていない実測を 0.0 で埋めない**（R1.5-C4・19周目）。
    # ここは `== 0.0` と「誤差 100%・重大な乖離」を期待していたが、metrics が
    # 丸ごと無いこの入力では CTR を一度も計測していない。
    # 「CTR 0% だったので予測が 100% 外れた」は計測していない判定そのもので、
    # 管理者通知まで飛ばしていた。
    assert result["actual"]["ctr"] is None
    # elapsed_hours の 30 は届いているが、CTR が無い＝実測として成立していないので
    # actual レーン全体を実測扱いしない（30 だけ残すと「実測がある」に見える）
    assert result["actual"]["elapsed_hours"] is None
    assert result["actual"]["is_real"] is False
    assert result["actual"]["data_source"] == "unavailable"
    assert result["analysis"]["checked"] is False
    assert result["analysis"]["significant_deviation"] is None
    assert result["status"] == "skipped"
    mock_manager._save.assert_not_called()

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
    # **届いていない実測を 0.0 で埋めない**（R1.5-C4・19周目）。
    # metrics はあるが click_through_rate が無いので、CTR は計測できていない。
    # 以前はここでも 0.0 が「実測 CTR」になり、重大な乖離という判定が出ていた。
    assert result["actual"]["ctr"] is None
    assert result["actual"]["is_real"] is False
    assert result["actual"]["data_source"] == "unavailable"
    assert result["analysis"]["checked"] is False
    assert result["analysis"]["significant_deviation"] is None
    assert result["status"] == "skipped"
    mock_manager._save.assert_not_called()

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
    # **届いていない実測を 0.0 で埋めない**（R1.5-C4・19周目）。
    # actual_metrics が None なので実測は1つも無い。
    assert result["actual"]["ctr"] is None
    assert result["actual"]["is_real"] is False
    assert result["actual"]["data_source"] == "unavailable"
    # **誤差率 0.0 / 乖離なし、を期待していた行がまさに捏造のピン留めだった。**
    # 予測 CTR が 0 以下だと誤差率は割り算できないのに、以前は error_margin = 0 へ
    # 落として significant_deviation を False にし、「予測が当たった」に見せていた。
    # 判定していないので、いまはどちらも None が返る。
    assert result["analysis"]["checked"] is False
    assert result["analysis"]["error_margin_pct"] is None
    assert result["analysis"]["significant_deviation"] is None
    assert result["status"] == "skipped"
    mock_manager._save.assert_not_called()

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
