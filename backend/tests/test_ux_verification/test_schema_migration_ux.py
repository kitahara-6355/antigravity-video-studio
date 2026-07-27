import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
from ux_verification import schema_migration

# Test for migrate_story_v1_to_v2
def test_migrate_story_v1_to_v2():
    story_v1 = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [],
        "verification_items": []
    }
    story_v2 = schema_migration.migrate_story_v1_to_v2(story_v1)
    assert story_v2["$schema_version"] == "2.0"
    assert story_v2["lifecycle"]["status"] == "active"
    assert story_v2["persona_context"]["origin_persona"] == "step_001_mirei"
    assert story_v2["data_requirements"] == []
    assert story_v2["inheritance"]["mode"] == "inherit"
    assert story_v2["philosophy_derived_edges"] == []

    story_v1_existing = {
        "$schema_version": "2.1",
        "lifecycle": {"status": "draft", "created_at": "2026-05-01"},
        "persona_context": {"origin_persona": "custom_persona"},
        "data_requirements": [{"key": "value"}],
        "inheritance": {"mode": "override"}
    }
    story_v2_existing = schema_migration.migrate_story_v1_to_v2(story_v1_existing)
    assert story_v2_existing["$schema_version"] == "2.1"
    assert story_v2_existing["lifecycle"]["status"] == "draft"
    assert story_v2_existing["persona_context"]["origin_persona"] == "custom_persona"
    assert story_v2_existing["data_requirements"] == [{"key": "value"}]
    assert story_v2_existing["inheritance"]["mode"] == "override"

# Test for is_v2
def test_is_v2():
    assert schema_migration.is_v2({"$schema_version": "2.0"}) is True
    assert schema_migration.is_v2({"$schema_version": "1.0"}) is False
    assert schema_migration.is_v2({}) is False

# Test for validate_v2_schema
def test_validate_v2_schema():
    valid_story = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [{"id": 1, "text": "Scene 1", "linked_items": ["item-1"]}],
        "verification_items": [
            {
                "id": "item-1",
                "layer": 1,
                "story_scene": 1,
                "description": "Verify",
                "test_method": "manual"
            }
        ],
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
        }
    }
    assert schema_migration.validate_v2_schema(valid_story) == []

    invalid_story_1 = {}
    errors = schema_migration.validate_v2_schema(invalid_story_1)
    assert any("必須フィールド 'ux_id' が存在しません" in err for err in errors)
    assert any("必須フィールド 'name' が存在しません" in err for err in errors)
    assert any("必須フィールド 'description' が存在しません" in err for err in errors)
    assert any("必須フィールド 'scenes' が存在しません" in err for err in errors)
    assert any("必須フィールド 'verification_items' が存在しません" in err for err in errors)
    assert any("$schema_version が '2.0' ではありません" in err for err in errors)
    assert any("lifecycle フィールドが存在しません" in err for err in errors)
    assert any("persona_context フィールドが存在しません" in err for err in errors)
    assert any("data_requirements フィールドが存在しません" in err for err in errors)
    assert any("inheritance フィールドが存在しません" in err for err in errors)

    invalid_story_2 = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [],
        "verification_items": [],
        "$schema_version": "2.0",
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
        }
    }
    errors_2 = schema_migration.validate_v2_schema(invalid_story_2)
    assert any("lifecycle.status が無効です" in err for err in errors_2)
    assert any("lifecycle.created_at が空です" in err for err in errors_2)
    assert any("persona_context.origin_step が整数ではありません" in err for err in errors_2)
    assert any("persona_context.origin_persona が空です" in err for err in errors_2)
    assert any("inheritance.mode が無効です" in err for err in errors_2)

    invalid_story_3 = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [{}],
        "verification_items": [],
        "$schema_version": "2.0",
        "lifecycle": {"status": "active", "created_at": "2026-04-30"},
        "persona_context": {"origin_step": 1, "origin_persona": "step_001_mirei"},
        "data_requirements": [],
        "inheritance": {"mode": "inherit"}
    }
    errors_3 = schema_migration.validate_v2_schema(invalid_story_3)
    assert any("scenes[0] に id がありません" in err for err in errors_3)
    assert any("scenes[0] に text がありません" in err for err in errors_3)
    assert any("scenes[0] に linked_items がありません" in err for err in errors_3)

    invalid_story_4 = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [],
        "verification_items": [
            {
                "layer": 6
            }
        ],
        "$schema_version": "2.0",
        "lifecycle": {"status": "active", "created_at": "2026-04-30"},
        "persona_context": {"origin_step": 1, "origin_persona": "step_001_mirei"},
        "data_requirements": [],
        "inheritance": {"mode": "inherit"}
    }
    errors_4 = schema_migration.validate_v2_schema(invalid_story_4)
    assert any("verification_items[0] に id がありません" in err for err in errors_4)
    assert any("verification_items[0] に story_scene がありません" in err for err in errors_4)
    assert any("verification_items[0] に description がありません" in err for err in errors_4)
    assert any("verification_items[0] に test_method がありません" in err for err in errors_4)
    assert any("verification_items[0] の layer が 1-5 の範囲外です" in err for err in errors_4)

# Test for validate_persona_json
def test_validate_persona_json(tmp_path):
    non_existent = tmp_path / "ghost.json"
    errors = schema_migration.validate_persona_json(non_existent)
    assert any("ファイルが存在しません" in err for err in errors)

    p_file = tmp_path / "persona.json"
    # 不正なJSONのテスト（L202-203 カバレッジ用）
    with open(p_file, "w", encoding="utf-8") as f:
        f.write("{corrupted_persona_json")
    errors = schema_migration.validate_persona_json(p_file)
    assert any("ファイルの読み込みまたはJSONの解析に失敗しました" in err for err in errors)

    with open(p_file, "w", encoding="utf-8") as f:
        json.dump({}, f)
    errors = schema_migration.validate_persona_json(p_file)
    assert any("必須フィールド 'step' が存在しません" in err for err in errors)

    with open(p_file, "w", encoding="utf-8") as f:
        json.dump({
            "step": "one",
            "persona_id": "p1",
            "name": "Name",
            "profile": "Profile",
            "ux_principles": [],
            "maturity_dimensions": {},
            "ux_stories": []
        }, f)
    errors = schema_migration.validate_persona_json(p_file)
    assert any("step が整数ではありません" in err for err in errors)

    with open(p_file, "w", encoding="utf-8") as f:
        json.dump({
            "step": 1,
            "persona_id": "p1",
            "name": "Name",
            "profile": "Profile",
            "ux_principles": [],
            "maturity_dimensions": {
                "D1_activity": 1
            },
            "ux_stories": [1]
        }, f)
    errors = schema_migration.validate_persona_json(p_file)
    assert any("maturity_dimensions に不足" in err for err in errors)

    with open(p_file, "w", encoding="utf-8") as f:
        json.dump({
            "step": 1,
            "persona_id": "p1",
            "name": "Name",
            "profile": "Profile",
            "ux_principles": [],
            "maturity_dimensions": {
                "D1_activity": 1, "D2_judgment": 1, "D3_philosophy": 1, "D4_youtube": 1, "D5_proficiency": 1
            },
            "ux_stories": []
        }, f)
    errors = schema_migration.validate_persona_json(p_file)
    assert any("ux_stories が空またはリストではありません" in err for err in errors)

    with open(p_file, "w", encoding="utf-8") as f:
        json.dump({
            "step": 1,
            "persona_id": "p1",
            "name": "Name",
            "profile": "Profile",
            "ux_principles": [],
            "maturity_dimensions": {
                "D1_activity": 1, "D2_judgment": 1, "D3_philosophy": 1, "D4_youtube": 1, "D5_proficiency": 1
            },
            "ux_stories": ["STORY-001"]
        }, f)
    assert schema_migration.validate_persona_json(p_file) == []

# Test migrate_all_stories with dry_run and error conditions
def test_migrate_all_stories(tmp_path):
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()

    v2_story = {
        "$schema_version": "2.0",
        "ux_id": "STORY-002",
        "name": "Story 2",
        "description": "Story 2 desc",
        "scenes": [],
        "verification_items": []
    }
    with open(stories_dir / "story_v2.json", "w", encoding="utf-8") as f:
        json.dump(v2_story, f)

    v1_story_valid = {
        "ux_id": "STORY-001",
        "name": "Story 1",
        "description": "Story 1 desc",
        "scenes": [{"id": 1, "text": "Scene 1", "linked_items": ["item-1"]}],
        "verification_items": [
            {
                "id": "item-1",
                "layer": 1,
                "story_scene": 1,
                "description": "Verify",
                "test_method": "manual"
            }
        ]
    }
    with open(stories_dir / "story_v1_valid.json", "w", encoding="utf-8") as f:
        json.dump(v1_story_valid, f)

    v1_story_invalid = {
        "ux_id": "STORY-003",
        "name": "Story 3",
        "description": "Story 3 desc",
        "scenes": [{}],
        "verification_items": []
    }
    with open(stories_dir / "story_v1_invalid.json", "w", encoding="utf-8") as f:
        json.dump(v1_story_invalid, f)

    # 不正なJSONのテスト（L160-165 カバレッジ用）
    with open(stories_dir / "story_corrupted.json", "w", encoding="utf-8") as f:
        f.write("{corrupted_story_json")

    with patch.object(schema_migration, "STORIES_DIR", stories_dir):
        results = schema_migration.migrate_all_stories(dry_run=True)
        
        assert "story_v2.json" in results["already_v2"]
        assert "story_v1_valid.json" in results["migrated"]
        assert any(err["file"] == "story_v1_invalid.json" for err in results["errors"])
        assert any(err["file"] == "story_corrupted.json" and "ファイルの読み込みまたはJSONの解析に失敗しました" in err["errors"][0] for err in results["errors"])

        with open(stories_dir / "story_v1_valid.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "$schema_version" not in data

    with patch.object(schema_migration, "STORIES_DIR", stories_dir):
        results = schema_migration.migrate_all_stories(dry_run=False)
        assert "story_v1_valid.json" in results["migrated"]

        with open(stories_dir / "story_v1_valid.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["$schema_version"] == "2.0"

# CLI tests using runpy with truediv mock to redirect stories evaluation
def test_cli_main_dry_run(monkeypatch, tmp_path):
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()

    # 既に v2
    with open(stories_dir / "already_v2.json", "w", encoding="utf-8") as f:
        json.dump({"$schema_version": "2.0", "ux_id": "STORY-001", "name": "Story 1", "description": "Desc 1", "scenes": [], "verification_items": []}, f)
    # 正常移行可能な v1
    v1_valid = {
        "ux_id": "STORY-002",
        "name": "Story 2",
        "description": "Desc 2",
        "scenes": [{"id": 1, "text": "Scene 1", "linked_items": ["item-1"]}],
        "verification_items": [{"id": "item-1", "layer": 1, "story_scene": 1, "description": "Verify", "test_method": "manual"}]
    }
    with open(stories_dir / "v1_valid.json", "w", encoding="utf-8") as f:
        json.dump(v1_valid, f)
    # エラーになる v1
    v1_invalid = {"ux_id": "STORY-003", "name": "Story 3", "description": "Desc 3", "scenes": [{}]}
    with open(stories_dir / "v1_invalid.json", "w", encoding="utf-8") as f:
        json.dump(v1_invalid, f)

    # Path / "stories" を一時ディレクトリの stories_dir に解決する
    original_truediv = Path.__truediv__
    def mock_truediv(self, other):
        if other == "stories":
            return stories_dir
        return original_truediv(self, other)

    monkeypatch.setattr(Path, "__truediv__", mock_truediv)
    monkeypatch.setattr(sys, "argv", ["schema_migration.py"])

    runpy.run_path(
        str(Path(schema_migration.__file__)),
        run_name="__main__"
    )
    
    # ドライランなので v1_valid に schema_version が追加されていないこと
    with open(stories_dir / "v1_valid.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "$schema_version" not in data

def test_cli_main_apply(monkeypatch, tmp_path):
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()

    # 既に v2
    with open(stories_dir / "already_v2.json", "w", encoding="utf-8") as f:
        json.dump({"$schema_version": "2.0", "ux_id": "STORY-001", "name": "Story 1", "description": "Desc 1", "scenes": [], "verification_items": []}, f)
    # 正常移行可能な v1
    v1_valid = {
        "ux_id": "STORY-002",
        "name": "Story 2",
        "description": "Desc 2",
        "scenes": [{"id": 1, "text": "Scene 1", "linked_items": ["item-1"]}],
        "verification_items": [{"id": "item-1", "layer": 1, "story_scene": 1, "description": "Verify", "test_method": "manual"}]
    }
    with open(stories_dir / "v1_valid.json", "w", encoding="utf-8") as f:
        json.dump(v1_valid, f)
    # エラーになる v1
    v1_invalid = {"ux_id": "STORY-003", "name": "Story 3", "description": "Desc 3", "scenes": [{}]}
    with open(stories_dir / "v1_invalid.json", "w", encoding="utf-8") as f:
        json.dump(v1_invalid, f)

    # Path / "stories" を一時ディレクトリの stories_dir に解決する
    original_truediv = Path.__truediv__
    def mock_truediv(self, other):
        if other == "stories":
            return stories_dir
        return original_truediv(self, other)

    monkeypatch.setattr(Path, "__truediv__", mock_truediv)
    monkeypatch.setattr(sys, "argv", ["schema_migration.py", "--apply"])

    runpy.run_path(
        str(Path(schema_migration.__file__)),
        run_name="__main__"
    )
    
    # 適用されたので v1_valid に schema_version が追加されていること
    with open(stories_dir / "v1_valid.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["$schema_version"] == "2.0"


def test_cli_main_success(monkeypatch, tmp_path):
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()

    # 既に v2
    with open(stories_dir / "already_v2.json", "w", encoding="utf-8") as f:
        json.dump({"$schema_version": "2.0", "ux_id": "STORY-001", "name": "Story 1", "description": "Desc 1", "scenes": [], "verification_items": []}, f)
    # 正常移行可能な v1
    v1_valid = {
        "ux_id": "STORY-002",
        "name": "Story 2",
        "description": "Desc 2",
        "scenes": [{"id": 1, "text": "Scene 1", "linked_items": ["item-1"]}],
        "verification_items": [{"id": "item-1", "layer": 1, "story_scene": 1, "description": "Verify", "test_method": "manual"}]
    }
    with open(stories_dir / "v1_valid.json", "w", encoding="utf-8") as f:
        json.dump(v1_valid, f)

    # Path / "stories" を一時ディレクトリの stories_dir に解決する
    original_truediv = Path.__truediv__
    def mock_truediv(self, other):
        if other == "stories":
            return stories_dir
        return original_truediv(self, other)

    monkeypatch.setattr(Path, "__truediv__", mock_truediv)
    
    # 1. ドライランの実行（エラーなし）
    monkeypatch.setattr(sys, "argv", ["schema_migration.py"])
    runpy.run_path(
        str(Path(schema_migration.__file__)),
        run_name="__main__"
    )
    with open(stories_dir / "v1_valid.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "$schema_version" not in data

    # 2. applyの実行（エラーなし）
    monkeypatch.setattr(sys, "argv", ["schema_migration.py", "--apply"])
    runpy.run_path(
        str(Path(schema_migration.__file__)),
        run_name="__main__"
    )
    with open(stories_dir / "v1_valid.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["$schema_version"] == "2.0"


# Extra edge cases for validate_v2_schema and validate_persona_json
def test_validate_v2_schema_extra_edge_cases():
    story_invalid_layer_type = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [],
        "verification_items": [
            {
                "id": "item-1",
                "layer": "3",  # 文字列型
                "story_scene": 1,
                "description": "Verify",
                "test_method": "manual"
            }
        ],
        "$schema_version": "2.0",
        "lifecycle": {"status": "active", "created_at": "2026-04-30"},
        "persona_context": {"origin_step": 1, "origin_persona": "step_001_mirei"},
        "data_requirements": [],
        "inheritance": {"mode": "inherit"}
    }
    errors = schema_migration.validate_v2_schema(story_invalid_layer_type)
    assert any("layer が 1-5 の範囲外です" in err for err in errors)

    story_invalid_layer_float = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [],
        "verification_items": [
            {
                "id": "item-1",
                "layer": 2.5,  # 浮動小数点数
                "story_scene": 1,
                "description": "Verify",
                "test_method": "manual"
            }
        ],
        "$schema_version": "2.0",
        "lifecycle": {"status": "active", "created_at": "2026-04-30"},
        "persona_context": {"origin_step": 1, "origin_persona": "step_001_mirei"},
        "data_requirements": [],
        "inheritance": {"mode": "inherit"}
    }
    errors = schema_migration.validate_v2_schema(story_invalid_layer_float)
    assert any("layer が 1-5 の範囲外です" in err for err in errors)

def test_validate_persona_json_extra_edge_cases(tmp_path):
    p_file = tmp_path / "persona.json"
    with open(p_file, "w", encoding="utf-8") as f:
        import json
        json.dump({
            "step": 1,
            "persona_id": "p1",
            "name": "Name",
            "profile": "Profile",
            "ux_principles": [],
            "maturity_dimensions": {
                "D1_activity": 1, "D2_judgment": 1, "D3_philosophy": 1, "D4_youtube": 1, "D5_proficiency": 1
            },
            "ux_stories": "not_a_list_but_a_string"
        }, f)
    errors = schema_migration.validate_persona_json(p_file)
    assert any("ux_stories が空またはリストではありません" in err for err in errors)


def test_migrate_story_v1_to_v2_partial_dict():
    story_v1 = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": [],
        "verification_items": [],
        "lifecycle": {
            "status": "draft"
        },
        "persona_context": {
            "origin_persona": "custom_persona"
        },
        "inheritance": {
            "mode": "override"
        }
    }
    story_v2 = schema_migration.migrate_story_v1_to_v2(story_v1)
    
    assert story_v2["lifecycle"]["created_at"] == schema_migration.MIGRATION_DATE
    assert story_v2["persona_context"]["origin_step"] == 1
    assert story_v2["inheritance"]["override_policy"] == "extend_only"
    
    errors = schema_migration.validate_v2_schema(story_v2)
    assert errors == []

def test_validate_v2_schema_invalid_types():
    errors = schema_migration.validate_v2_schema("not_a_dict")
    assert any("ストーリーデータが辞書" in err for err in errors)

    story_invalid_types = {
        "ux_id": "STORY-001",
        "name": "Test Story",
        "description": "Test Description",
        "scenes": "not_a_list",
        "verification_items": [
            "not_a_dict"
        ],
        "$schema_version": "2.0",
        "lifecycle": "not_a_dict",
        "persona_context": "not_a_dict",
        "data_requirements": [],
        "inheritance": "not_a_dict"
    }
    errors = schema_migration.validate_v2_schema(story_invalid_types)
    assert any("lifecycle フィールドが辞書ではありません" in err for err in errors)
    assert any("persona_context フィールドが辞書ではありません" in err for err in errors)
    assert any("inheritance フィールドが辞書ではありません" in err for err in errors)
    assert any("scenes フィールドがリストではありません" in err for err in errors)
    assert any("verification_items[0] が辞書ではありません" in err for err in errors)

def test_validate_persona_json_invalid_types(tmp_path):
    p_file = tmp_path / "persona_invalid_md.json"
    with open(p_file, "w", encoding="utf-8") as f:
        import json
        json.dump({
            "step": 1,
            "persona_id": "mirei",
            "name": "Mirei",
            "profile": "Profile",
            "ux_principles": [],
            "maturity_dimensions": "not_a_dict",
            "ux_stories": ["UX-001"]
        }, f)
        
    errors = schema_migration.validate_persona_json(p_file)
    assert any("maturity_dimensions が辞書ではありません" in err for err in errors)


def test_migrate_story_v1_to_v2_invalid_type():
    res = schema_migration.migrate_story_v1_to_v2("not_a_dict")
    assert res == {}


def test_is_v2_invalid_type():
    assert schema_migration.is_v2("not_a_dict") is False
    assert schema_migration.is_v2(None) is False


def test_validate_persona_json_not_dict(tmp_path):
    p_file = tmp_path / "persona_list.json"
    with open(p_file, "w", encoding="utf-8") as f:
        import json
        json.dump([1, 2, 3], f)  # Not a dictionary
    errors = schema_migration.validate_persona_json(p_file)
    assert any("ペルソナデータが辞書型ではありません" in err for err in errors)


def test_migrate_all_stories_invalid_dict_file(tmp_path):
    # Temp stories directory
    stories_dir = tmp_path / "stories"
    stories_dir.mkdir()
    
    # Write an invalid file (list instead of dict)
    with open(stories_dir / "invalid.json", "w", encoding="utf-8") as f:
        import json
        json.dump([1, 2, 3], f)
        
    with patch.object(schema_migration, "STORIES_DIR", stories_dir):
        results = schema_migration.migrate_all_stories(dry_run=True)
        assert len(results["errors"]) == 1
        assert "ストーリーデータが辞書型ではありません" in results["errors"][0]["errors"][0]

