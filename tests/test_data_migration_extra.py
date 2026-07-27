import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from backend.data_migration import DataMigration

@pytest.fixture
def migration():
    return DataMigration()

def test_verify_design_tokens_all_moods_missing(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    data = {"design_tokens": {"some_other_mood": {}}}
    constitution_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "warning"
    assert "Missing moods" in res["reason"]
    for mood in ["elegant", "dynamic", "dramatic"]:
        assert mood in res["reason"]

def test_verify_design_tokens_invalid_type_in_json(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    data = {"design_tokens": "not_a_dict_but_a_string"}
    constitution_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "failed"
    assert "design_tokens section is not a JSON object" in res["reason"]

def test_verify_evolution_log_exists_os_error(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    log_path = migration._branding_dir / "evolution_log.json"
    log_path.touch()
    
    with patch("builtins.open", side_effect=OSError("Read permission denied")):
        res = migration._verify_evolution_log(dry_run=False)
        assert res["status"] == "failed"
        assert "evolution_log.json is corrupted" in res["reason"]
        assert "Read permission denied" in res["reason"]

def test_verify_model_config_multiple_keys_missing(migration, tmp_path):
    migration._backend_dir = tmp_path
    config_path = tmp_path / "model_config.json"
    data = {"task_mapping": {}}
    config_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_model_config()
    assert res["status"] == "warning"
    assert "Missing keys" in res["reason"]
    assert "version" in res["reason"]
    assert "models" in res["reason"]
    assert "task_mapping" not in res["reason"]

def test_verify_plugins_zero_plugins(migration, tmp_path):
    migration._backend_dir = tmp_path
    plugins_path = tmp_path / "plugins"
    plugins_path.mkdir()
    
    res = migration._verify_plugins()
    assert res["status"] == "warning"
    assert "Only 0 plugins found" in res["reason"]

def test_verify_core_multiple_files_missing(migration, tmp_path):
    migration._backend_dir = tmp_path
    core_path = tmp_path / "core"
    core_path.mkdir()
    (core_path / "__init__.py").touch()
    
    res = migration._verify_core()
    assert res["status"] == "failed"
    assert "Missing files" in res["reason"]
    assert "context.py" in res["reason"]
    assert "plugin.py" in res["reason"]
    assert "registry.py" in res["reason"]
    assert "__init__.py" not in res["reason"]
