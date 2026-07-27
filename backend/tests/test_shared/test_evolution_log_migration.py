import logging
import pytest
from utils.evolution_log_migration import (
    migrate_evolution_log,
    CURRENT_SCHEMA_VERSION,
    _SCHEMA_2_0_DEFAULTS
)

def test_migrate_already_current_version():
    log = {"schema_version": CURRENT_SCHEMA_VERSION, "entries": ["test"]}
    result = migrate_evolution_log(log)
    assert result is log
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    assert "philosophies" not in result

def test_migrate_no_version(caplog):
    log = {}
    with caplog.at_level(logging.INFO):
        result = migrate_evolution_log(log)
    
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    for k, v in _SCHEMA_2_0_DEFAULTS.items():
        assert result[k] == v
    
    assert "[EvolutionLogMigration] schema_version\u672a\u8a2d\u5b9a \u2192 2.0\u306b\u30de\u30a4\u30b0\u30ec\u30fc\u30b7\u30e7\u30f3" in caplog.text

def test_migrate_old_version(caplog):
    log = {"schema_version": "1.0"}
    with caplog.at_level(logging.INFO):
        result = migrate_evolution_log(log)
        
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    for k, v in _SCHEMA_2_0_DEFAULTS.items():
        assert result[k] == v
        
    assert "[EvolutionLogMigration] schema_version 1.0 \u2192 2.0" in caplog.text

def test_migrate_non_destructive():
    log = {
        "schema_version": "1.0",
        "entries": ["existing_entry"],
        "trust_score": 1.5,
    }
    result = migrate_evolution_log(log)
    
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    assert result["entries"] == ["existing_entry"]
    assert result["trust_score"] == 1.5
    assert result["philosophies"] == []
    assert result["decision_insights"] == []
