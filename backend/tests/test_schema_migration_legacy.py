import pytest
import json
import runpy
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parents[2]
backend_dir = project_root / 'backend'
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.ux_verification.schema_migration import (
    migrate_story_v1_to_v2,
    is_v2,
    validate_v2_schema,
    migrate_all_stories,
    validate_persona_json,
    MIGRATION_DATE
)

# -------------------------------------------------------------
# 1. is_v2 のテスト
# -------------------------------------------------------------
def test_is_v2():
    assert is_v2({"$schema_version": "2.0"}) is True
    assert is_v2({"$schema_version": "1.0"}) is False
    assert is_v2({}) is False

# -------------------------------------------------------------
# 2. migrate_story_v1_to_v2 のテスト
# -------------------------------------------------------------
def test_migrate_story_v1_to_v2():
    v1_story = {
        "ux_id": "UX-001",
        "name": "Test Story",
        "description": "Desc",
        "scenes": [],
        "verification_items": []
    }
    
    v2_story = migrate_story_v1_to_v2(v1_story)
    
    assert v2_story["$schema_version"] == "2.0"
    assert v2_story["lifecycle"]["status"] == "active"
    assert v2_story["lifecycle"]["created_at"] == MIGRATION_DATE
    assert v2_story["persona_context"]["origin_persona"] == "step_001_mirei"
    assert v2_story["data_requirements"] == []
    assert v2_story["inheritance"]["mode"] == "inherit"
    assert v2_story["philosophy_derived_edges"] == []
    assert v2_story["analytics_derived_edges"] == []
    assert v2_story["major_update_refs"] == []
    
    assert v2_story["ux_id"] == "UX-001"
    
    v1_story_with_values = {
        "ux_id": "UX-002",
        "$schema_version": "already_v2_temp",
        "lifecycle": {"status": "draft", "created_at": "2026-01-01"},
        "persona_context": {"origin_step": 3, "origin_persona": "step_003_taro"},
        "data_requirements": [{"db": "prod"}],
        "inheritance": {"mode": "override"}
    }
    
    v2_migrated = migrate_story_v1_to_v2(v1_story_with_values)
    assert v2_migrated["$schema_version"] == "already_v2_temp"
    assert v2_migrated["lifecycle"]["status"] == "draft"
    assert v2_migrated["lifecycle"]["created_at"] == "2026-01-01"
    assert v2_migrated["persona_context"]["origin_persona"] == "step_003_taro"
    assert v2_migrated["data_requirements"] == [{"db": "prod"}]
    assert v2_migrated["inheritance"]["mode"] == "override"

# -------------------------------------------------------------
# 3. validate_v2_schema のテスト
# -------------------------------------------------------------
def test_validate_v2_schema_valid():
    valid_story = {
        "ux_id": "UX-001",
        "name": "Test Story",
        "description": "Desc",
        "$schema_version": "2.0",
        "lifecycle": {
            "status": "active",
            "created_at": "2026-04-30"
        },
        "persona_context": {
            "origin_step": 1,
            "origin_persona": "step_001_mirei"
        },
        "data_requirements": [],
        "inheritance": {
            "mode": "inherit"
        },
        "scenes": [
            {"id": 1, "text": "Scene 1", "linked_items": ["item1"]}
        ],
        "verification_items": [
            {
                "id": "item1",
                "layer": 3,
                "story_scene": 1,
                "description": "Verify detail",
                "test_method": "auto"
            }
        ]
    }
    errors = validate_v2_schema(valid_story)
    assert errors == []

def test_validate_v2_schema_missing_fields():
    invalid_story = {}
    errors = validate_v2_schema(invalid_story)
    assert any("ux_id" in e for e in errors)
    assert any("$schema_version" in e for e in errors)
    assert any("lifecycle" in e for e in errors)
    assert any("persona_context" in e for e in errors)
    assert any("data_requirements" in e for e in errors)
    assert any("inheritance" in e for e in errors)

def test_validate_v2_schema_invalid_values():
    invalid_story = {
        "ux_id": "UX-001",
        "name": "Test Story",
        "description": "Desc",
        "$schema_version": "1.0",
        "lifecycle": {
            "status": "invalid_status",
            "created_at": ""
        },
        "persona_context": {
            "origin_step": "not_an_int",
            "origin_persona": ""
        },
        "data_requirements": [],
        "inheritance": {
            "mode": "invalid_mode"
        },
        "scenes": [
            {"text": "Missing id and linked_items"},
            {"id": 2, "linked_items": []}
        ],
        "verification_items": [
            {
                "id": "item1",
                "layer": 6,
                "story_scene": 1,
                "description": "Verify detail"
            }
        ]
    }
    errors = validate_v2_schema(invalid_story)
    
    assert any("$schema_version が '2.0' ではありません" in e for e in errors)
    assert any("lifecycle.status が無効です" in e for e in errors)
    assert any("lifecycle.created_at が空です" in e for e in errors)
    assert any("persona_context.origin_step が整数ではありません" in e for e in errors)
    assert any("persona_context.origin_persona が空です" in e for e in errors)
    assert any("inheritance.mode が無効です" in e for e in errors)
    assert any("scenes[0] に id がありません" in e for e in errors)
    assert any("scenes[0] に linked_items がありません" in e for e in errors)
    assert any("scenes[1] に text がありません" in e for e in errors)
    assert any("verification_items[0] に test_method がありません" in e for e in errors)
    assert any("verification_items[0] の layer が 1-5 の範囲外です" in e for e in errors)

# -------------------------------------------------------------
# 4. migrate_all_stories のテスト
# -------------------------------------------------------------
def test_migrate_all_stories(tmp_path, monkeypatch):
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()
    
    v2_data = {
        "ux_id": "UX-v2", "name": "V2", "description": "d",
        "$schema_version": "2.0",
        "lifecycle": {"status": "active", "created_at": MIGRATION_DATE},
        "persona_context": {"origin_step": 1, "origin_persona": "p"},
        "data_requirements": [], "inheritance": {"mode": "inherit"},
        "scenes": [], "verification_items": []
    }
    with open(stories_dir / "story_already_v2.json", "w", encoding="utf-8") as f:
        json.dump(v2_data, f)
        
    v1_data = {
        "ux_id": "UX-v1", "name": "V1", "description": "d",
        "scenes": [], "verification_items": []
    }
    with open(stories_dir / "story_v1_valid.json", "w", encoding="utf-8") as f:
        json.dump(v1_data, f)
        
    v1_invalid_data = {
        "ux_id": "UX-v1-invalid", "name": "V1 Invalid",
        "scenes": [], "verification_items": []
    }
    with open(stories_dir / "story_v1_invalid.json", "w", encoding="utf-8") as f:
        json.dump(v1_invalid_data, f)
        
    import backend.ux_verification.schema_migration as sm
    monkeypatch.setattr(sm, "STORIES_DIR", stories_dir)
    
    res_dry = sm.migrate_all_stories(dry_run=True)
    
    assert "story_already_v2.json" in res_dry["already_v2"]
    assert "story_v1_valid.json" in res_dry["migrated"]
    assert len(res_dry["errors"]) == 1
    assert res_dry["errors"][0]["file"] == "story_v1_invalid.json"
    
    with open(stories_dir / "story_v1_valid.json", "r", encoding="utf-8") as f:
        loaded = json.load(f)
        assert loaded.get("$schema_version") is None
        
    res_apply = sm.migrate_all_stories(dry_run=False)
    
    assert "story_already_v2.json" in res_apply["already_v2"]
    assert "story_v1_valid.json" in res_apply["migrated"]
    
    with open(stories_dir / "story_v1_valid.json", "r", encoding="utf-8") as f:
        loaded = json.load(f)
        assert loaded.get("$schema_version") == "2.0"

# -------------------------------------------------------------
# 5. validate_persona_json のテスト
# -------------------------------------------------------------
def test_validate_persona_json(tmp_path):
    non_existent = tmp_path / "non_existent.json"
    errors = validate_persona_json(non_existent)
    assert len(errors) == 1
    assert "ファイルが存在しません" in errors[0]
    
    valid_persona = {
        "step": 1,
        "persona_id": "mirei",
        "name": "Mirei",
        "profile": "Profile",
        "ux_principles": [],
        "maturity_dimensions": {
            "D1_activity": 1,
            "D2_judgment": 1,
            "D3_philosophy": 1,
            "D4_youtube": 1,
            "D5_proficiency": 1
        },
        "ux_stories": ["UX-001"]
    }
    persona_path = tmp_path / "persona_valid.json"
    with open(persona_path, "w", encoding="utf-8") as f:
        json.dump(valid_persona, f)
        
    errors = validate_persona_json(persona_path)
    assert errors == []
    
    invalid_persona = {
        "step": "not_an_int",
        "persona_id": "mirei",
        "profile": "Profile",
        "ux_principles": [],
        "maturity_dimensions": {
            "D1_activity": 1
        },
        "ux_stories": []
    }
    invalid_path = tmp_path / "persona_invalid.json"
    with open(invalid_path, "w", encoding="utf-8") as f:
        json.dump(invalid_persona, f)
        
    errors = validate_persona_json(invalid_path)
    assert any("必須フィールド 'name' が存在しません" in e for e in errors)
    assert any("step が整数ではありません" in e for e in errors)
    assert any("maturity_dimensions に不足" in e for e in errors)
    assert any("ux_stories が空またはリストではありません" in e for e in errors)

# -------------------------------------------------------------
# 6. if __name__ == "__main__": ブロックのテスト
# -------------------------------------------------------------
def test_main_block(monkeypatch, tmp_path):
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()
    
    # 正常な v1 データを置いてマイグレーションされるようにする
    v1_data = {
        "ux_id": "UX-v1", "name": "V1", "description": "d",
        "scenes": [], "verification_items": []
    }
    with open(stories_dir / "story_v1_valid.json", "w", encoding="utf-8") as f:
        json.dump(v1_data, f)
        
    # すでに v2 のデータ
    v2_data = {
        "ux_id": "UX-v2", "name": "V2", "description": "d",
        "$schema_version": "2.0",
        "lifecycle": {"status": "active", "created_at": MIGRATION_DATE},
        "persona_context": {"origin_step": 1, "origin_persona": "p"},
        "data_requirements": [], "inheritance": {"mode": "inherit"},
        "scenes": [], "verification_items": []
    }
    with open(stories_dir / "story_already_v2.json", "w", encoding="utf-8") as f:
        json.dump(v2_data, f)
        
    # エラーが出る v1 データ
    v1_invalid_data = {
        "ux_id": "UX-v1-invalid", "name": "V1 Invalid",
        "scenes": [], "verification_items": []
    }
    with open(stories_dir / "story_v1_invalid.json", "w", encoding="utf-8") as f:
        json.dump(v1_invalid_data, f)
        
    # Path.glob を monkeypatch して、stories ディレクトリに対する glob を一時ディレクトリに差し替える
    original_glob = Path.glob
    def mock_glob(self, pattern):
        if "stories" in self.parts or self.name == "stories":
            return original_glob(stories_dir, pattern)
        return original_glob(self, pattern)
    
    monkeypatch.setattr(Path, "glob", mock_glob)
    
    import backend.ux_verification.schema_migration as sm
    monkeypatch.setattr(sys, "argv", ["schema_migration.py"])
    res = runpy.run_path(str(Path(sm.__file__)), run_name="__main__")
    assert res is not None

    monkeypatch.setattr(sys, "argv", ["schema_migration.py", "--apply"])
    res_apply = runpy.run_path(str(Path(sm.__file__)), run_name="__main__")
    assert res_apply is not None


# -------------------------------------------------------------
# 7. エラーハンドリングのテスト
# -------------------------------------------------------------
def test_migrate_all_stories_invalid_json(tmp_path, monkeypatch):
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()
    
    # 破損した JSON データ（構文エラー）
    with open(stories_dir / "story_corrupted.json", "w", encoding="utf-8") as f:
        f.write("{ invalid json")
        
    import backend.ux_verification.schema_migration as sm
    monkeypatch.setattr(sm, "STORIES_DIR", stories_dir)
    
    res = sm.migrate_all_stories(dry_run=True)
    assert len(res["errors"]) == 1
    assert res["errors"][0]["file"] == "story_corrupted.json"
    assert "ファイルの読み込みまたはJSONの解析に失敗しました" in res["errors"][0]["errors"][0]


def test_validate_persona_json_corrupted(tmp_path):
    p_file = tmp_path / "persona_corrupted.json"
    with open(p_file, "w", encoding="utf-8") as f:
        f.write("{ corrupted persona")
        
    errors = validate_persona_json(p_file)
    assert len(errors) == 1
    assert "ファイルの読み込みまたはJSONの解析に失敗しました" in errors[0]

# -------------------------------------------------------------
# 8. 追加のテストケース
# -------------------------------------------------------------
def test_migrate_story_v1_to_v2_missing_keys():
    # 必須キーが欠落している v1 ストーリーをマイグレーションし、バリデーションエラーを検出するテスト
    story_v1 = {
        "ux_id": "UX-MISSING",
    }
    story_v2 = migrate_story_v1_to_v2(story_v1)
    errors = validate_v2_schema(story_v2)
    
    assert any("必須フィールド 'name' が存在しません" in e for e in errors)
    assert any("必須フィールド 'description' が存在しません" in e for e in errors)
    assert any("必須フィールド 'scenes' が存在しません" in e for e in errors)
    assert any("必須フィールド 'verification_items' が存在しません" in e for e in errors)

