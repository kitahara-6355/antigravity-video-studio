import logging
from backend.utils.evolution_log_migration import migrate_evolution_log, CURRENT_SCHEMA_VERSION, _SCHEMA_2_0_DEFAULTS

def test_migrate_already_current_version():
    # パスA: すでに現行バージョンである場合、そのままリターンされること
    data = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "custom_field": "custom_value"
    }
    result = migrate_evolution_log(data)
    
    assert result == data
    # 早期リターンされるため、他の必須フィールドが追加されていないことを確認
    assert "entries" not in result
    assert "trust_score" not in result


def test_migrate_no_schema_version(caplog):
    # パスB: schema_versionが未設定（None）の場合、2.0に昇格しデフォルト値が設定されること
    data = {
        "existing_key": "existing_value"
    }
    
    with caplog.at_level(logging.INFO):
        result = migrate_evolution_log(data)
        
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    assert result["existing_key"] == "existing_value"
    
    # 全てのデフォルト値が設定されていることを確認
    for key, val in _SCHEMA_2_0_DEFAULTS.items():
        assert key in result
        assert result[key] == val
        
    # ロギングの確認
    assert any("[EvolutionLogMigration] schema_version未設定 → 2.0にマイグレーション" in record.message for record in caplog.records)


def test_migrate_old_schema_version(caplog):
    # パスC: schema_versionが古いバージョン（例: "1.0"）の場合、2.0に昇格しデフォルト値が設定されること
    data = {
        "schema_version": "1.0",
        "existing_key": "existing_value"
    }
    
    with caplog.at_level(logging.INFO):
        result = migrate_evolution_log(data)
        
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    assert result["existing_key"] == "existing_value"
    
    # 全てのデフォルト値が設定されていることを確認
    for key, val in _SCHEMA_2_0_DEFAULTS.items():
        assert key in result
        assert result[key] == val
        
    # ロギングの確認
    assert any("[EvolutionLogMigration] schema_version 1.0 → 2.0" in record.message for record in caplog.records)


def test_migrate_non_destructive():
    # パスD: 既存フィールド値が存在する場合に、既存データが非破壊的に維持されることを検証するテスト
    data = {
        "schema_version": "1.0",
        "entries": [{"id": 1, "action": "test"}],
        "trust_score": 10.0,
        "director_profile": {"name": "TestDirector"},
        "rejection_count": 5
    }
    
    result = migrate_evolution_log(data)
    
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    # 既存のデータが上書きされず、そのまま残っていること
    assert result["entries"] == [{"id": 1, "action": "test"}]
    assert result["trust_score"] == 10.0
    assert result["director_profile"] == {"name": "TestDirector"}
    assert result["rejection_count"] == 5
    
    # 欠落しているフィールドのみデフォルト値が設定されること
    assert result["philosophies"] == []
    assert result["decision_insights"] == []


def test_migrate_none_input():
    # 入力が None の場合、新規に空辞書が作られてスキーマ 2.0 にマイグレーションされること
    result = migrate_evolution_log(None)
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION
    for key, val in _SCHEMA_2_0_DEFAULTS.items():
        assert key in result
        assert result[key] == val


def test_migrate_invalid_type_input():
    # 入力が辞書型または None ではない場合に TypeError が送出されること
    import pytest
    with pytest.raises(TypeError) as excinfo:
        migrate_evolution_log("invalid_string")  # type: ignore
    assert "evo_log must be a dictionary or None" in str(excinfo.value)

    with pytest.raises(TypeError):
        migrate_evolution_log([1, 2, 3])  # type: ignore



def test_migrate_immutable_input_logging(caplog):
    # イミュータブルな辞書型（MappingProxyType）を渡した際、
    # 例外が送出され、かつ例外ログが記録されることの検証
    from types import MappingProxyType
    
    # スキーマバージョンが古いものにし、マイグレーションが走るようにする
    raw_data = {
        "schema_version": "1.0",
        "existing_key": "existing_value"
    }
    immutable_data = MappingProxyType(raw_data)
    
    with caplog.at_level(logging.ERROR):
        import pytest
        with pytest.raises(TypeError):
            migrate_evolution_log(immutable_data)  # type: ignore
            
    assert any("[EvolutionLogMigration] マイグレーション実行中に例外が発生しました" in record.message for record in caplog.records)
