"""
M3.7 PCQA基盤テスト — ペルソナ/スキーマ/偽PASS検出

タスク1: step_001_mirei.json スキーマ検証
タスク2: L2 v2.0 マイグレーション検証
タスク3: 偽PASS検出ゲート検証
"""
import json
import tempfile
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ux_verification.schema_migration import (
    migrate_story_v1_to_v2,
    is_v2,
    validate_v2_schema,
    migrate_all_stories,
    validate_persona_json,
)
from ux_verification.quality_gates.fake_pass_detector import (
    scan_file_for_patterns,
    scan_file_for_assertion_density,
    scan_directory,
    FakePassViolation,
    FakePassReport,
)


# ============================================================
# タスク1: ペルソナ step_001_mirei.json 検証
# ============================================================

PERSONA_PATH = Path(__file__).parent.parent / "ux_verification" / "personas" / "step_001_mirei.json"


class TestPersonaValidation:
    """ペルソナ定義のスキーマ検証"""

    def test_persona_file_exists(self):
        """step_001_mirei.json が存在する"""
        assert PERSONA_PATH.exists(), f"ペルソナファイルが見つかりません: {PERSONA_PATH}"

    def test_persona_valid_json(self):
        """有効なJSONとして読み込める"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        assert isinstance(persona, dict)

    def test_persona_schema_validation(self):
        """バリデーション関数がエラーゼロを返す"""
        errors = validate_persona_json(PERSONA_PATH)
        assert errors == [], f"バリデーションエラー: {errors}"

    def test_persona_step_is_1(self):
        """Step 1として定義されている"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        assert persona["step"] == 1

    def test_persona_id_format(self):
        """persona_id が step_001_mirei"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        assert persona["persona_id"] == "step_001_mirei"

    def test_persona_name_is_mirei(self):
        """名前が北原美麗"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        assert persona["name"] == "北原美麗"

    def test_persona_has_5_dimensions(self):
        """5次元成熟度モデルが完備"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        dims = persona["maturity_dimensions"]
        expected = {"D1_activity", "D2_judgment", "D3_philosophy", "D4_youtube", "D5_proficiency"}
        assert set(dims.keys()) == expected

    def test_persona_initial_scores_zero(self):
        """初期スコアが全て0"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        for dim_key, dim_val in persona["maturity_dimensions"].items():
            assert dim_val["score"] == 0, f"{dim_key} の初期スコアが0ではない: {dim_val['score']}"

    def test_persona_covers_all_12_stories(self):
        """O-1〜O-12の全12ストーリーをカバー"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        expected = {f"O-{i}" for i in range(1, 13)}
        actual = set(persona["ux_stories"])
        assert expected == actual, f"不足: {expected - actual}, 余剰: {actual - expected}"

    def test_persona_ux_principles_non_empty(self):
        """UX原則が空でない"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        assert len(persona["ux_principles"]) >= 3

    def test_persona_step_thresholds_exist(self):
        """進化閾値が定義されている"""
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            persona = json.load(f)
        assert "step_thresholds" in persona
        assert "advance_to_step_5" in persona["step_thresholds"]


# ============================================================
# タスク2: L2 v2.0 スキーママイグレーション検証
# ============================================================

STORIES_DIR = Path(__file__).parent.parent / "ux_verification" / "stories"


class TestSchemaMigration:
    """L2ゴール v1.0→v2.0 マイグレーション検証"""

    def test_v1_story_is_detected_as_not_v2(self):
        """v1.0ストーリーはis_v2=False"""
        v1 = {"ux_id": "O-1", "name": "test"}
        assert not is_v2(v1)

    def test_v2_story_is_detected_as_v2(self):
        """v2.0ストーリーはis_v2=True"""
        v2 = {"ux_id": "O-1", "name": "test", "$schema_version": "2.0"}
        assert is_v2(v2)

    def test_migration_adds_schema_version(self):
        """マイグレーション後に$schema_version=2.0が設定される"""
        v1 = {"ux_id": "O-1", "name": "test", "description": "d",
               "scenes": [], "verification_items": []}
        v2 = migrate_story_v1_to_v2(v1)
        assert v2["$schema_version"] == "2.0"

    def test_migration_adds_lifecycle(self):
        """マイグレーション後にlifecycleが追加される"""
        v1 = {"ux_id": "O-1", "name": "test", "description": "d",
               "scenes": [], "verification_items": []}
        v2 = migrate_story_v1_to_v2(v1)
        assert "lifecycle" in v2
        assert v2["lifecycle"]["status"] == "active"

    def test_migration_adds_persona_context(self):
        """マイグレーション後にpersona_contextが追加される"""
        v1 = {"ux_id": "O-1", "name": "test", "description": "d",
               "scenes": [], "verification_items": []}
        v2 = migrate_story_v1_to_v2(v1)
        assert v2["persona_context"]["origin_step"] == 1
        assert v2["persona_context"]["origin_persona"] == "step_001_mirei"

    def test_migration_adds_data_requirements(self):
        """マイグレーション後にdata_requirementsが追加される"""
        v1 = {"ux_id": "O-1", "name": "test", "description": "d",
               "scenes": [], "verification_items": []}
        v2 = migrate_story_v1_to_v2(v1)
        assert v2["data_requirements"] == []

    def test_migration_adds_inheritance(self):
        """マイグレーション後にinheritanceが追加される"""
        v1 = {"ux_id": "O-1", "name": "test", "description": "d",
               "scenes": [], "verification_items": []}
        v2 = migrate_story_v1_to_v2(v1)
        assert v2["inheritance"]["mode"] == "inherit"
        assert v2["inheritance"]["override_policy"] == "extend_only"

    def test_migration_preserves_existing_fields(self):
        """マイグレーション後に既存フィールドが保持される"""
        v1 = {"ux_id": "O-4", "name": "SmartCut", "description": "desc",
               "scenes": [{"id": "S1", "text": "test", "linked_items": []}],
               "verification_items": [{"id": "X-1", "layer": 1,
                                        "story_scene": "S1", "description": "d",
                                        "test_method": "dom_exists"}]}
        v2 = migrate_story_v1_to_v2(v1)
        assert v2["ux_id"] == "O-4"
        assert v2["name"] == "SmartCut"
        assert len(v2["scenes"]) == 1
        assert len(v2["verification_items"]) == 1

    def test_migration_is_idempotent(self):
        """二度マイグレーションしても結果が変わらない"""
        v1 = {"ux_id": "O-1", "name": "test", "description": "d",
               "scenes": [], "verification_items": []}
        v2a = migrate_story_v1_to_v2(v1)
        v2b = migrate_story_v1_to_v2(v2a)
        assert v2a == v2b

    def test_validate_v2_passes_for_valid_story(self):
        """有効なv2.0ストーリーはバリデーションPASS"""
        v1 = {"ux_id": "O-1", "name": "test", "description": "d",
               "scenes": [{"id": "S1", "text": "t", "linked_items": []}],
               "verification_items": [{"id": "X-1", "layer": 1,
                                        "story_scene": "S1", "description": "d",
                                        "test_method": "dom"}]}
        v2 = migrate_story_v1_to_v2(v1)
        errors = validate_v2_schema(v2)
        assert errors == [], f"バリデーションエラー: {errors}"

    def test_validate_v2_fails_for_missing_lifecycle(self):
        """lifecycleなしでバリデーションFAIL"""
        story = {"ux_id": "O-1", "name": "t", "description": "d",
                 "$schema_version": "2.0",
                 "scenes": [], "verification_items": [],
                 "persona_context": {"origin_step": 1, "origin_persona": "x"},
                 "data_requirements": [],
                 "inheritance": {"mode": "inherit"}}
        errors = validate_v2_schema(story)
        assert any("lifecycle" in e for e in errors)

    def test_all_stories_migration_dry_run(self):
        """全ストーリーのドライランマイグレーションが成功する"""
        results = migrate_all_stories(dry_run=True)
        assert len(results["errors"]) == 0, f"エラー: {results['errors']}"
        expected_total = len(list(STORIES_DIR.glob("*.json")))
        total = len(results["migrated"]) + len(results["already_v2"])
        assert total == expected_total, f"期待{expected_total}ファイル、実際{total}ファイル"


# ============================================================
# タスク3: 偽PASS検出ゲート検証
# ============================================================

class TestFakePassDetector:
    """偽PASS検出ゲートの検証"""

    def test_detects_or_true(self, tmp_path):
        """'or True' パターンを検出する"""
        test_file = tmp_path / "test_fake.py"
        test_file.write_text("def test_x():\n    assert response.ok or True\n", encoding="utf-8")
        violations = scan_file_for_patterns(test_file)
        assert len(violations) >= 1
        assert any(v.pattern == "or True" for v in violations)

    def test_detects_assert_true(self, tmp_path):
        """'assert True' パターンを検出する"""
        test_file = tmp_path / "test_fake.py"
        test_file.write_text("def test_x():\n    assert True\n", encoding="utf-8")
        violations = scan_file_for_patterns(test_file)
        assert len(violations) >= 1
        assert any(v.pattern == "assert True" for v in violations)

    def test_detects_assert_1(self, tmp_path):
        """'assert 1' パターンを検出する"""
        test_file = tmp_path / "test_fake.py"
        test_file.write_text("def test_x():\n    assert 1\n", encoding="utf-8")
        violations = scan_file_for_patterns(test_file)
        assert len(violations) >= 1
        assert any(v.pattern == "assert 1" for v in violations)

    def test_no_false_positive_on_valid_assert(self, tmp_path):
        """正常なassertを誤検出しない"""
        test_file = tmp_path / "test_valid.py"
        test_file.write_text(
            "def test_x():\n"
            "    assert response.status_code == 200\n"
            "    assert 'data' in result\n",
            encoding="utf-8",
        )
        violations = scan_file_for_patterns(test_file)
        critical = [v for v in violations if v.severity == "critical"]
        assert len(critical) == 0

    def test_detects_low_assertion_density(self, tmp_path):
        """アサーション密度が低いテストを検出する"""
        test_file = tmp_path / "test_empty.py"
        test_file.write_text(
            "def test_nothing():\n"
            "    x = 1 + 1\n"
            "    print(x)\n",
            encoding="utf-8",
        )
        violations = scan_file_for_assertion_density(test_file)
        assert len(violations) >= 1
        assert violations[0].pattern == "low_assertion_density"

    def test_no_density_warning_for_valid_test(self, tmp_path):
        """十分なアサーションがあるテストは警告しない"""
        test_file = tmp_path / "test_ok.py"
        test_file.write_text(
            "def test_valid():\n"
            "    result = compute()\n"
            "    assert result == 42\n",
            encoding="utf-8",
        )
        violations = scan_file_for_assertion_density(test_file)
        assert len(violations) == 0

    def test_scan_directory_returns_report(self, tmp_path):
        """ディレクトリスキャンがFakePassReportを返す"""
        test_file = tmp_path / "test_e2e_sample.py"
        test_file.write_text(
            "def test_ok():\n    assert 1 == 1\n",
            encoding="utf-8",
        )
        report = scan_directory(tmp_path, pattern="test_e2e_*.py")
        assert isinstance(report, FakePassReport)
        assert report.files_scanned >= 1

    def test_report_properties(self):
        """FakePassReportのプロパティが正しく動作する"""
        report = FakePassReport()
        assert not report.has_violations
        assert report.critical_count == 0
        
        report.violations.append(
            FakePassViolation("f.py", 1, "test_x", "or True", "critical", "d")
        )
        assert report.has_violations
        assert report.critical_count == 1
        assert report.warning_count == 0

    def test_existing_e2e_tests_pass_gate(self):
        """既存E2Eテストが偽PASSゲートをPASS（criticalゼロ）"""
        e2e_dir = Path(__file__).parent / "e2e"
        if not e2e_dir.exists():
            pytest.skip("E2Eディレクトリが存在しない")
        report = scan_directory(e2e_dir)
        assert report.critical_count == 0, (
            f"既存E2Eテストに偽PASSが検出されました: "
            f"{[v for v in report.violations if v.severity == 'critical']}"
        )

    def test_decode_error_and_os_error_handling(self, tmp_path):
        """デコードエラーやOSErrorが発生した際の例外ハンドリングを検証"""
        # 存在しないパス
        non_existent = tmp_path / "non_existent_file.py"
        violations_pattern = scan_file_for_patterns(non_existent)
        violations_density = scan_file_for_assertion_density(non_existent)
        assert violations_pattern == []
        assert violations_density == []

        # デコードエラーを起こすバイナリファイル
        binary_file = tmp_path / "test_bin.py"
        binary_file.write_bytes(b"\xff\xfe\x00\x00def test_x(): pass")
        violations_pattern = scan_file_for_patterns(binary_file)
        violations_density = scan_file_for_assertion_density(binary_file)
        assert violations_pattern == []
        assert violations_density == []

    def test_syntax_error_in_assertion_density(self, tmp_path):
        """構文エラーを含むファイルの例外ハンドリングを検証"""
        syntax_error_file = tmp_path / "test_syntax.py"
        syntax_error_file.write_text("def test_x(:\n    assert True", encoding="utf-8")
        violations = scan_file_for_assertion_density(syntax_error_file)
        assert violations == []

    def test_non_test_function_pass_only(self, tmp_path):
        """test_で始まらない関数内でのpass-onlyが無視されることを検証"""
        test_file = tmp_path / "test_ignore_pass.py"
        test_file.write_text(
            "def helper_func():\n"
            "    pass\n"
            "def test_func():\n"
            "    assert 1 == 1\n",
            encoding="utf-8"
        )
        violations = scan_file_for_patterns(test_file)
        assert len(violations) == 0

    def test_pytest_assertion_calls(self, tmp_path):
        """pytestやmockの各種アサーション呼び出しの認識を検証"""
        test_file = tmp_path / "test_calls.py"
        test_file.write_text(
            "def test_calls():\n"
            "    import pytest\n"
            "    with pytest.raises(ValueError):\n"
            "        pass\n"
            "    mock_obj.assert_called_once()\n"
            "    mock_obj.assert_called_with(1)\n"
            "    mock_obj.assert_called_once_with(2)\n"
            "    mock_obj.assert_not_called()\n"
            "    mock_obj.assert_any_call()\n"
            "    mock_obj.assert_has_calls()\n"
            "    with pytest.warns(UserWarning):\n"
            "        pass\n"
            "    mock_obj.assert_called()\n",
            encoding="utf-8"
        )
        violations = scan_file_for_assertion_density(test_file)
        assert len(violations) == 0

    def test_scan_directory_with_parse_error(self, tmp_path):
        """scan_directory内でのパースエラー発生時のスキップを検証"""
        syntax_err = tmp_path / "test_e2e_syntax_err.py"
        syntax_err.write_text("def test_x(:\n", encoding="utf-8")
        
        ok_file = tmp_path / "test_e2e_ok.py"
        ok_file.write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
        
        report = scan_directory(tmp_path, pattern="test_e2e_*.py")
        assert report.files_scanned == 2
        assert report.functions_scanned == 1

    def test_format_report_variations(self):
        """format_reportのすべてのフォーマットパスを検証"""
        from ux_verification.quality_gates.fake_pass_detector import format_report
        
        report_ok = FakePassReport()
        report_ok.files_scanned = 1
        report_ok.functions_scanned = 2
        formatted_ok = format_report(report_ok)
        assert "偽PASSパターンは検出されませんでした" in formatted_ok
        assert "スキャンファイル数: 1" in formatted_ok

        report_err = FakePassReport()
        report_err.files_scanned = 2
        report_err.functions_scanned = 4
        report_err.violations.append(
            FakePassViolation("test_file.py", 10, "test_func", "or True", "critical", "critical error detail")
        )
        report_err.violations.append(
            FakePassViolation("test_file.py", 15, "test_func2", "pass-only", "warning", "warning detail")
        )
        formatted_err = format_report(report_err)
        assert "以下の偽PASSパターンが検出されました" in formatted_err
        assert "🔴 test_file.py:10 (test_func)" in formatted_err
        assert "🟡 test_file.py:15 (test_func2)" in formatted_err
        assert "Critical: 1, Warning: 1" in formatted_err

    def test_main_function_e2e_dir_missing(self, tmp_path):
        """main関数に存在しないディレクトリを渡したときの挙動"""
        from ux_verification.quality_gates.fake_pass_detector import main
        non_existent_dir = tmp_path / "non_existent_e2e"
        ret = main(["fake_pass_detector.py", str(non_existent_dir)])
        assert ret == 0

    def test_main_function_runs_successfully(self, tmp_path):
        """main関数が正常に動作し終了コードを返すことの検証"""
        from ux_verification.quality_gates.fake_pass_detector import main
        
        ok_file = tmp_path / "test_e2e_ok.py"
        ok_file.write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
        
        ret_ok = main(["fake_pass_detector.py", str(tmp_path)])
        assert ret_ok == 0

        err_file = tmp_path / "test_e2e_err.py"
        err_file.write_text("def test_err():\n    assert True\n", encoding="utf-8")
        
        ret_err = main(["fake_pass_detector.py", str(tmp_path)])
        assert ret_err == 1

