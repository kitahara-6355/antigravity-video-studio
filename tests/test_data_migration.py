import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from backend.data_migration import DataMigration, data_migration


@pytest.fixture
def migration():
    return DataMigration()


def test_run_migration_dry_run_success(migration):
    # すべてのチェックが正常にパスする場合
    with patch.object(migration, "_verify_design_tokens", return_value={"name": "design_tokens", "status": "passed"}),          patch.object(migration, "_verify_evolution_log", return_value={"name": "evolution_log", "status": "passed"}),          patch.object(migration, "_verify_model_config", return_value={"name": "model_config", "status": "passed"}),          patch.object(migration, "_verify_plugins", return_value={"name": "plugins", "status": "passed"}),          patch.object(migration, "_verify_core", return_value={"name": "core", "status": "passed"}):
        
        res = migration.run_migration(dry_run=True)
        assert res["status"] == "completed"
        assert "checks passed" in res["summary"]
        assert not any(s["name"] == "backup" for s in res["steps"])


def test_run_migration_real_success(migration):
    # dry_run=Falseで、バックアップと検証がすべて正常にパスする場合
    with patch.object(migration, "_create_backup", return_value="/tmp/backup_path") as mock_backup,          patch.object(migration, "_verify_design_tokens", return_value={"name": "design_tokens", "status": "passed"}),          patch.object(migration, "_verify_evolution_log", return_value={"name": "evolution_log", "status": "passed"}),          patch.object(migration, "_verify_model_config", return_value={"name": "model_config", "status": "passed"}),          patch.object(migration, "_verify_plugins", return_value={"name": "plugins", "status": "passed"}),          patch.object(migration, "_verify_core", return_value={"name": "core", "status": "passed"}):
        
        res = migration.run_migration(dry_run=False)
        mock_backup.assert_called_once()
        assert res["status"] == "completed"
        assert any(s["name"] == "backup" and s["status"] == "completed" for s in res["steps"])


def test_run_migration_backup_error(migration):
    # バックアップ作成でOSErrorが発生した場合
    with patch.object(migration, "_create_backup", side_effect=OSError("Disk full")):
        res = migration.run_migration(dry_run=False)
        assert res["status"] == "failed"
        assert "Backup creation failed" in res["summary"]
        assert any(s["name"] == "backup" and s["status"] == "failed" for s in res["steps"])


def test_create_backup_success(migration, tmp_path):
    # バックアップが正常に行われるかの実地テスト
    migration._backup_dir = tmp_path / "migration_backups"
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    
    # ダミーファイルの作成
    dummy_file = migration._branding_dir / "constitution.json"
    dummy_file.write_text("{}", encoding="utf-8")
    
    backup_path_str = migration._create_backup()
    backup_path = Path(backup_path_str)
    
    assert backup_path.exists()
    assert (backup_path / "branding" / "constitution.json").exists()


def test_create_backup_no_branding_dir(migration, tmp_path):
    # brandingディレクトリが存在しない場合のバックアップ実地テスト
    migration._backup_dir = tmp_path / "migration_backups"
    migration._branding_dir = tmp_path / "branding"
    
    backup_path_str = migration._create_backup()
    backup_path = Path(backup_path_str)
    
    # プロダクションコードの仕様上、brandingが存在しない場合はbackup_pathディレクトリ自体は作成されない
    assert not backup_path.exists()
    assert migration._backup_dir.exists()
    assert not (backup_path / "branding").exists()


def test_create_backup_os_error(migration):
    # バックアップ作成でmkdirがOSErrorを投げるケース
    with patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
        with pytest.raises(OSError):
            migration._create_backup()


def test_verify_design_tokens_no_file(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    res = migration._verify_design_tokens()
    assert res["status"] == "failed"
    assert "constitution.json not found" in res["reason"]


def test_verify_design_tokens_empty(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    constitution_path.write_text("{}", encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "failed"
    assert "design_tokens section is empty" in res["reason"]


def test_verify_design_tokens_missing_moods(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    data = {"design_tokens": {"elegant": {}, "dramatic": {}}}
    constitution_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "warning"
    assert "Missing moods" in res["reason"]
    assert "dynamic" in res["reason"]


def test_verify_design_tokens_passed(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    data = {"design_tokens": {"elegant": {}, "dynamic": {}, "dramatic": {}}}
    constitution_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "passed"
    assert "elegant" in res["moods"]


def test_verify_design_tokens_json_decode_error(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    constitution_path.write_text("corrupted json", encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "failed"


def test_verify_evolution_log_create_dir_error(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    with patch.object(Path, "mkdir", side_effect=OSError("Read-only file system")):
        res = migration._verify_evolution_log(dry_run=False)
        assert res["status"] == "failed"
        assert "Failed to create branding directory" in res["reason"]


def test_verify_evolution_log_write_error(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        res = migration._verify_evolution_log(dry_run=False)
        assert res["status"] == "failed"
        assert "Failed to create evolution log" in res["reason"]


def test_verify_evolution_log_write_error_unlink_fails(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    # replaceがOSErrorを投げ、かつunlinkもOSErrorを投げることで
    # tmp_path.unlink()の例外ハンドラ（except OSError: pass）を通す
    with patch.object(Path, "replace", side_effect=OSError("Replace failed")), \
         patch.object(Path, "unlink", side_effect=OSError("Unlink failed")):
        
        res = migration._verify_evolution_log(dry_run=False)
        assert res["status"] == "failed"
        assert "Failed to create evolution log" in res["reason"]


def test_verify_evolution_log_created_success(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    res = migration._verify_evolution_log(dry_run=False)
    assert res["status"] == "passed"
    assert res["action"] == "created"
    assert (migration._branding_dir / "evolution_log.json").exists()


def test_verify_evolution_log_exists_and_valid(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    log_path = migration._branding_dir / "evolution_log.json"
    log_path.write_text(json.dumps({"version": "4.0"}), encoding="utf-8")
    
    res = migration._verify_evolution_log(dry_run=False)
    assert res["status"] == "passed"
    assert res["action"] == "exists"


def test_verify_evolution_log_corrupted(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    log_path = migration._branding_dir / "evolution_log.json"
    log_path.write_text("broken json", encoding="utf-8")
    
    res = migration._verify_evolution_log(dry_run=False)
    assert res["status"] == "failed"
    assert "evolution_log.json is corrupted" in res["reason"]


def test_verify_evolution_log_dry_run_will_create(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    # evolution_log.json が存在しない状態で dry_run=True の場合
    res = migration._verify_evolution_log(dry_run=True)
    assert res["status"] == "passed"
    assert res["action"] == "will_create"
    # ファイルもディレクトリも作成されていないこと
    assert not migration._branding_dir.exists()
    assert not (migration._branding_dir / "evolution_log.json").exists()


def test_verify_evolution_log_dry_run_exists(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    log_path = migration._branding_dir / "evolution_log.json"
    log_path.write_text(json.dumps({"version": "4.0"}), encoding="utf-8")
    
    # evolution_log.json が既に存在し、dry_run=True の場合
    res = migration._verify_evolution_log(dry_run=True)
    assert res["status"] == "passed"
    assert res["action"] == "exists"


def test_verify_model_config_no_file(migration, tmp_path):
    migration._backend_dir = tmp_path
    res = migration._verify_model_config()
    assert res["status"] == "failed"
    assert "model_config.json not found" in res["reason"]


def test_verify_model_config_json_decode_error(migration, tmp_path):
    migration._backend_dir = tmp_path
    config_path = tmp_path / "model_config.json"
    config_path.write_text("invalid", encoding="utf-8")
    
    res = migration._verify_model_config()
    assert res["status"] == "failed"


def test_verify_model_config_missing_keys(migration, tmp_path):
    migration._backend_dir = tmp_path
    config_path = tmp_path / "model_config.json"
    data = {"models": {}, "task_mapping": {}}
    config_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_model_config()
    assert res["status"] == "warning"
    assert "Missing keys" in res["reason"]
    assert "version" in res["reason"]


def test_verify_model_config_passed(migration, tmp_path):
    migration._backend_dir = tmp_path
    config_path = tmp_path / "model_config.json"
    data = {"version": "1.0", "models": {}, "task_mapping": {}}
    config_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_model_config()
    assert res["status"] == "passed"
    assert res["version"] == "1.0"


def test_verify_plugins_not_found(migration, tmp_path):
    migration._backend_dir = tmp_path
    res = migration._verify_plugins()
    assert res["status"] == "failed"
    assert "plugins directory not found" in res["reason"]


def test_verify_plugins_not_directory(migration, tmp_path):
    migration._backend_dir = tmp_path
    plugins_path = tmp_path / "plugins"
    plugins_path.touch()
    
    res = migration._verify_plugins()
    assert res["status"] == "failed"
    assert "plugins path is not a directory" in res["reason"]


def test_verify_plugins_os_error(migration, tmp_path):
    migration._backend_dir = tmp_path
    plugins_path = tmp_path / "plugins"
    plugins_path.mkdir()
    
    with patch.object(Path, "glob", side_effect=OSError("Read error")):
        res = migration._verify_plugins()
        assert res["status"] == "failed"


def test_verify_plugins_warning(migration, tmp_path):
    migration._backend_dir = tmp_path
    plugins_path = tmp_path / "plugins"
    plugins_path.mkdir()
    (plugins_path / "a_plugin.py").touch()
    (plugins_path / "b_plugin.py").touch()
    
    res = migration._verify_plugins()
    assert res["status"] == "warning"
    assert "Only 2 plugins found" in res["reason"]


def test_verify_plugins_passed(migration, tmp_path):
    migration._backend_dir = tmp_path
    plugins_path = tmp_path / "plugins"
    plugins_path.mkdir()
    (plugins_path / "a_plugin.py").touch()
    (plugins_path / "b_plugin.py").touch()
    (plugins_path / "c_plugin.py").touch()
    
    res = migration._verify_plugins()
    assert res["status"] == "passed"
    assert res["count"] == 3


def test_verify_core_not_found(migration, tmp_path):
    migration._backend_dir = tmp_path
    res = migration._verify_core()
    assert res["status"] == "failed"
    assert "core directory not found" in res["reason"]


def test_verify_core_not_directory(migration, tmp_path):
    migration._backend_dir = tmp_path
    core_path = tmp_path / "core"
    core_path.touch()
    
    res = migration._verify_core()
    assert res["status"] == "failed"
    assert "core path is not a directory" in res["reason"]


def test_verify_core_os_error(migration, tmp_path):
    migration._backend_dir = tmp_path
    core_path = tmp_path / "core"
    core_path.mkdir()
    
    with patch.object(Path, "exists", side_effect=OSError("Access denied")):
        res = migration._verify_core()
        assert res["status"] == "failed"


def test_verify_core_missing_files(migration, tmp_path):
    migration._backend_dir = tmp_path
    core_path = tmp_path / "core"
    core_path.mkdir()
    (core_path / "context.py").touch()
    
    res = migration._verify_core()
    assert res["status"] == "failed"
    assert "Missing files" in res["reason"]


def test_verify_core_passed(migration, tmp_path):
    migration._backend_dir = tmp_path
    core_path = tmp_path / "core"
    core_path.mkdir()
    for f in ["context.py", "plugin.py", "registry.py", "__init__.py"]:
        (core_path / f).touch()
        
    res = migration._verify_core()
    assert res["status"] == "passed"


def test_singleton_instance():
    assert isinstance(data_migration, DataMigration)

def test_verify_design_tokens_not_a_dict(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    constitution_path.write_text("[]", encoding="utf-8")  # list instead of dict
    
    res = migration._verify_design_tokens()
    assert res["status"] == "failed"
    assert "constitution.json content is not a JSON object" in res["reason"]


def test_verify_model_config_not_a_dict(migration, tmp_path):
    migration._backend_dir = tmp_path
    config_path = tmp_path / "model_config.json"
    config_path.write_text("[]", encoding="utf-8")  # list instead of dict
    
    res = migration._verify_model_config()
    assert res["status"] == "failed"
    assert "model_config.json content is not a JSON object" in res["reason"]


def test_run_migration_checks_failed(migration):
    # いずれかのチェックが failed または warning を返す場合
    with patch.object(migration, "_verify_design_tokens", return_value={"name": "design_tokens", "status": "failed", "reason": "some error"}), \
         patch.object(migration, "_verify_evolution_log", return_value={"name": "evolution_log", "status": "passed"}), \
         patch.object(migration, "_verify_model_config", return_value={"name": "model_config", "status": "warning", "reason": "some warning"}), \
         patch.object(migration, "_verify_plugins", return_value={"name": "plugins", "status": "passed"}), \
         patch.object(migration, "_verify_core", return_value={"name": "core", "status": "passed"}):
        
        res = migration.run_migration(dry_run=True)
        assert res["status"] == "needs_attention"
        assert "3/5 checks passed" in res["summary"]


def test_verify_design_tokens_os_error(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    constitution_path.touch()
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        res = migration._verify_design_tokens()
        assert res["status"] == "failed"
        assert "Read error" in res["reason"]


def test_verify_model_config_os_error(migration, tmp_path):
    migration._backend_dir = tmp_path
    config_path = tmp_path / "model_config.json"
    config_path.touch()
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        res = migration._verify_model_config()
        assert res["status"] == "failed"
        assert "Read error" in res["reason"]


def test_create_backup_copytree_error(migration, tmp_path):
    migration._backup_dir = tmp_path / "migration_backups"
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    
    with patch("shutil.copytree", side_effect=OSError("Copy failed")):
        with pytest.raises(OSError, match="Copy failed"):
            migration._create_backup()


def test_verify_design_tokens_invalid_type_design_tokens(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    data = {"design_tokens": 123}
    constitution_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "failed"
    assert "design_tokens section is not a JSON object" in res["reason"]


def test_verify_evolution_log_non_dict(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    log_path = migration._branding_dir / "evolution_log.json"
    # 辞書型ではなくリスト型を書き込む
    log_path.write_text("[]", encoding="utf-8")
    
    res = migration._verify_evolution_log(dry_run=False)
    assert res["status"] == "failed"
    assert "evolution_log.json content is not a JSON object" in res["reason"]


def test_verify_plugins_with_directory(migration, tmp_path):
    migration._backend_dir = tmp_path
    plugins_path = tmp_path / "plugins"
    plugins_path.mkdir()
    # 通常のファイルを2つ作成
    (plugins_path / "a_plugin.py").touch()
    (plugins_path / "b_plugin.py").touch()
    # プラグイン名に合致するディレクトリを作成
    dir_plugin = plugins_path / "c_plugin.py"
    dir_plugin.mkdir()
    
    # ディレクトリは除外されるため、count は 2 になり warning となる
    res = migration._verify_plugins()
    assert res["status"] == "warning"
    assert "Only 2 plugins found" in res["reason"]


def test_verify_core_with_directory(migration, tmp_path):
    migration._backend_dir = tmp_path
    core_path = tmp_path / "core"
    core_path.mkdir()
    # ファイルではなく同名のディレクトリを作成する
    for f in ["context.py", "plugin.py", "registry.py", "__init__.py"]:
        (core_path / f).mkdir()
        
    res = migration._verify_core()
    assert res["status"] == "failed"
    assert "Missing files" in res["reason"]


def test_verify_design_tokens_string_type(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    constitution_path = migration._branding_dir / "constitution.json"
    data = {"design_tokens": "not_a_dict"}
    constitution_path.write_text(json.dumps(data), encoding="utf-8")
    
    res = migration._verify_design_tokens()
    assert res["status"] == "failed"
    assert "design_tokens section is not a JSON object" in res["reason"]


def test_verify_evolution_log_none_type(migration, tmp_path):
    migration._branding_dir = tmp_path / "branding"
    migration._branding_dir.mkdir()
    log_path = migration._branding_dir / "evolution_log.json"
    # nullを書き込む
    log_path.write_text("null", encoding="utf-8")
    
    res = migration._verify_evolution_log(dry_run=False)
    assert res["status"] == "failed"
    assert "evolution_log.json content is not a JSON object" in res["reason"]
