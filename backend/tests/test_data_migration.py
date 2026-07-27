import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from data_migration import DataMigration, data_migration

# Fixtures for setting up temporary test directories mimicking the backend layout
@pytest.fixture
def temp_backend(tmp_path):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    branding_dir = backend_dir / "branding"
    branding_dir.mkdir()
    plugins_dir = backend_dir / "plugins"
    plugins_dir.mkdir()
    core_dir = backend_dir / "core"
    core_dir.mkdir()
    
    # 正常なダミーファイルの作成
    # 1. constitution.json
    constitution = {
        "design_tokens": {
            "elegant": {},
            "dynamic": {},
            "dramatic": {}
        }
    }
    with open(branding_dir / "constitution.json", "w", encoding="utf-8") as f:
        json.dump(constitution, f)
        
    # 2. evolution_log.json
    evolution_log = {
        "version": "4.0",
        "entries": [],
        "philosophies": [],
        "created": "2026-06-15T00:00:00"
    }
    with open(branding_dir / "evolution_log.json", "w", encoding="utf-8") as f:
        json.dump(evolution_log, f)
        
    # 3. model_config.json
    model_config = {
        "version": "1.0",
        "models": {},
        "task_mapping": {}
    }
    with open(backend_dir / "model_config.json", "w", encoding="utf-8") as f:
        json.dump(model_config, f)
        
    # 4. plugins
    for i in range(3):
        (plugins_dir / f"test{i}_plugin.py").touch()
        
    # 5. core
    for name in ["context.py", "plugin.py", "registry.py", "__init__.py"]:
        (core_dir / name).touch()
        
    return backend_dir

def test_migration_dry_run_success(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    res = migration.run_migration(dry_run=True)
    assert res["status"] == "completed"
    assert "5/5 checks passed" in res["summary"]
    
def test_migration_run_success_with_backup(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    res = migration.run_migration(dry_run=False)
    assert res["status"] == "completed"
    assert any(s["name"] == "backup" and s["status"] == "completed" for s in res["steps"])
    assert (temp_backend / "migration_backups").exists()

def test_migration_backup_failed(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch.object(shutil, "copytree", side_effect=OSError("Disk full")):
        res = migration.run_migration(dry_run=False)
        assert res["status"] == "failed"
        assert "Backup creation failed" in res["summary"]

def test_migration_backup_unexpected_exception(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch.object(shutil, "copytree", side_effect=Exception("Unexpected shutil error")):
        with pytest.raises(Exception, match="Unexpected shutil error"):
            migration.run_migration(dry_run=False)

def test_migration_design_tokens_missing(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    (temp_backend / "branding" / "constitution.json").unlink()
    
    res = migration.run_migration(dry_run=True)
    assert res["status"] == "needs_attention"
    step = next(s for s in res["steps"] if s["name"] == "design_tokens")
    assert step["status"] == "failed"
    assert "constitution.json not found" in step["reason"]

def test_migration_design_tokens_invalid_json(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    with open(temp_backend / "branding" / "constitution.json", "w") as f:
        f.write("{invalid json")
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "design_tokens")
    assert step["status"] == "failed"

def test_migration_design_tokens_missing_moods(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    constitution = {"design_tokens": {"elegant": {}}}
    with open(temp_backend / "branding" / "constitution.json", "w") as f:
        json.dump(constitution, f)
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "design_tokens")
    assert step["status"] == "warning"
    assert "Missing moods" in step["reason"]

def test_migration_evolution_log_creation(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    log_file = temp_backend / "branding" / "evolution_log.json"
    log_file.unlink()
    
    # Dry run
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "evolution_log")
    assert step["status"] == "passed"
    assert step["action"] == "will_create"
    
    # Real run
    res = migration.run_migration(dry_run=False)
    step = next(s for s in res["steps"] if s["name"] == "evolution_log")
    assert step["status"] == "passed"
    assert step["action"] == "created"
    assert log_file.exists()

def test_migration_evolution_log_corrupted(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    with open(temp_backend / "branding" / "evolution_log.json", "w") as f:
        f.write("{corrupted")
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "evolution_log")
    assert step["status"] == "failed"

def test_migration_model_config_missing(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    (temp_backend / "model_config.json").unlink()
    
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "model_config")
    assert step["status"] == "failed"

def test_migration_model_config_missing_keys(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    with open(temp_backend / "model_config.json", "w") as f:
        json.dump({"version": "1.0"}, f)
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "model_config")
    assert step["status"] == "warning"
    assert "Missing keys" in step["reason"]

def test_migration_plugins_missing(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    for f in (temp_backend / "plugins").glob("*"):
        f.unlink()
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "plugins")
    assert step["status"] == "warning"

def test_migration_core_missing_files(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    (temp_backend / "core" / "context.py").unlink()
    
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "core")
    assert step["status"] == "failed"

def test_migration_unexpected_exception_in_verify(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    
    # _verify_design_tokensでTypeErrorを投げさせる
    with patch.object(migration, "_verify_design_tokens", side_effect=TypeError("Unexpected type")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "design_tokens")
        assert step["status"] == "failed"
        assert "Unexpected error during verification" in step["reason"]
        assert "Unexpected type" in step["reason"]
        
def test_singleton_instance():
    assert isinstance(data_migration, DataMigration)


def test_verify_design_tokens_not_a_dict(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with open(temp_backend / "branding" / "constitution.json", "w", encoding="utf-8") as f:
        json.dump([], f)  # list instead of dict
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "design_tokens")
    assert step["status"] == "failed"
    assert "constitution.json content is not a JSON object" in step["reason"]


def test_verify_design_tokens_invalid_type_design_tokens(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with open(temp_backend / "branding" / "constitution.json", "w", encoding="utf-8") as f:
        json.dump({"design_tokens": "string"}, f)
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "design_tokens")
    assert step["status"] == "failed"
    assert "design_tokens section is not a JSON object" in step["reason"]


def test_verify_design_tokens_empty(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with open(temp_backend / "branding" / "constitution.json", "w", encoding="utf-8") as f:
        json.dump({"design_tokens": {}}, f)
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "design_tokens")
    assert step["status"] == "failed"
    assert "design_tokens section is empty" in step["reason"]


def test_verify_design_tokens_unexpected_exception(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    # open が Exception を投げるケース
    with patch("builtins.open", side_effect=Exception("Unexpected token read error")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "design_tokens")
        assert step["status"] == "failed"
        assert "Unexpected error: Unexpected token read error" in step["reason"]


def test_verify_evolution_log_mkdir_error(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    (temp_backend / "branding" / "evolution_log.json").unlink()
    
    # バックアップ作成をモックして、mkdir が呼ばれないようにする
    # そのうえで Path.mkdir が OSError を投げるようにする
    with patch.object(migration, "_create_backup", return_value="/tmp/dummy_backup"), \
         patch.object(Path, "mkdir", side_effect=OSError("Read-only filesystem")):
        res = migration.run_migration(dry_run=False)
        step = next(s for s in res["steps"] if s["name"] == "evolution_log")
        assert step["status"] == "failed"
        assert "Failed to create branding directory" in step["reason"]


def test_verify_evolution_log_write_error(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    (temp_backend / "branding" / "evolution_log.json").unlink()
    
    # ファイル書き込みで OSError が発生する場合
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        res = migration.run_migration(dry_run=False)
        step = next(s for s in res["steps"] if s["name"] == "evolution_log")
        assert step["status"] == "failed"
        assert "Failed to create evolution log" in step["reason"]


def test_verify_evolution_log_write_error_unlink_fails(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    (temp_backend / "branding" / "evolution_log.json").unlink()
    
    # replace と unlink がともに OSError を投げるケース
    with patch.object(Path, "replace", side_effect=OSError("Replace failed")), \
         patch.object(Path, "unlink", side_effect=OSError("Unlink failed")):
        res = migration.run_migration(dry_run=False)
        step = next(s for s in res["steps"] if s["name"] == "evolution_log")
        assert step["status"] == "failed"
        assert "Failed to create evolution log" in step["reason"]


def test_verify_evolution_log_not_a_dict(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with open(temp_backend / "branding" / "evolution_log.json", "w", encoding="utf-8") as f:
        json.dump([], f)
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "evolution_log")
    assert step["status"] == "failed"
    assert "evolution_log.json content is not a JSON object" in step["reason"]


def test_verify_evolution_log_unexpected_exception(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch("builtins.open", side_effect=Exception("Unexpected evolution read error")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "evolution_log")
        assert step["status"] == "failed"
        assert "Unexpected error: Unexpected evolution read error" in step["reason"]


def test_verify_model_config_not_a_dict(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with open(temp_backend / "model_config.json", "w", encoding="utf-8") as f:
        json.dump([], f)
        
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "model_config")
    assert step["status"] == "failed"
    assert "model_config.json content is not a JSON object" in step["reason"]


def test_verify_model_config_unexpected_exception(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch("builtins.open", side_effect=Exception("Unexpected config read error")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "model_config")
        assert step["status"] == "failed"
        assert "Unexpected error: Unexpected config read error" in step["reason"]


def test_verify_plugins_not_found(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    shutil.rmtree(temp_backend / "plugins")
    
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "plugins")
    assert step["status"] == "failed"
    assert "plugins directory not found" in step["reason"]


def test_verify_plugins_not_directory(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    shutil.rmtree(temp_backend / "plugins")
    (temp_backend / "plugins").touch()
    
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "plugins")
    assert step["status"] == "failed"
    assert "plugins path is not a directory" in step["reason"]


def test_verify_plugins_unexpected_exception(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch.object(Path, "glob", side_effect=Exception("Unexpected glob error")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "plugins")
        assert step["status"] == "failed"
        assert "Unexpected error: Unexpected glob error" in step["reason"]


def test_verify_core_not_found(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    shutil.rmtree(temp_backend / "core")
    
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "core")
    assert step["status"] == "failed"
    assert "core directory not found" in step["reason"]


def test_verify_core_not_directory(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    shutil.rmtree(temp_backend / "core")
    (temp_backend / "core").touch()
    
    res = migration.run_migration(dry_run=True)
    step = next(s for s in res["steps"] if s["name"] == "core")
    assert step["status"] == "failed"
    assert "core path is not a directory" in step["reason"]


def test_verify_core_unexpected_exception(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch.object(Path, "exists", side_effect=Exception("Unexpected core exists error")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "core")
        assert step["status"] == "failed"
        assert "Unexpected error: Unexpected core exists error" in step["reason"]


def test_verify_plugins_os_error(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch.object(Path, "glob", side_effect=OSError("Glob access denied")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "plugins")
        assert step["status"] == "failed"
        assert "Glob access denied" in step["reason"]


def test_verify_core_os_error(temp_backend):
    migration = DataMigration()
    migration._backend_dir = temp_backend
    migration._branding_dir = temp_backend / "branding"
    migration._backup_dir = temp_backend / "migration_backups"
    
    with patch.object(Path, "exists", side_effect=OSError("Exists check failed")):
        res = migration.run_migration(dry_run=True)
        step = next(s for s in res["steps"] if s["name"] == "core")
        assert step["status"] == "failed"
        assert "Exists check failed" in step["reason"]
