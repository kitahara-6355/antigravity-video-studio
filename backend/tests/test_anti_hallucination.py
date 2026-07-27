"""
test_anti_hallucination.py — AntiHallucinationGate のテスト

空想リスク排除の自己検証レイヤーが正しく機能することを検証する。
架空データの投入、証拠なしPASS、e2e_results.jsonとの不整合を検出できるか確認。
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from backend.ux_verification.anti_hallucination_gate import (
    AntiHallucinationGate,
    IntegrityReport,
    IntegrityViolation,
)


@pytest.fixture
def tmp_snapshots(tmp_path):
    """テスト用スナップショットディレクトリを作成"""
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    return snapshots_dir


@pytest.fixture
def tmp_e2e_results(tmp_path):
    """テスト用e2e_results.jsonを作成"""
    path = tmp_path / "e2e_results.json"
    data = {
        "dom_checks": {"O1-L1-01": True, "O1-L1-02": False},
        "visual_checks": {"O1-L2-01": True},
        "interaction_checks": {"O1-L3-01": False},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def gate(tmp_snapshots, tmp_e2e_results, tmp_path):
    """テスト用ゲートインスタンス"""
    harness_path = tmp_path / "harness_audit_status.json"
    return AntiHallucinationGate(
        snapshots_dir=tmp_snapshots,
        e2e_results_path=tmp_e2e_results,
        harness_status_path=harness_path,
    )


class TestSnapshotIntegrity:
    """スナップショットの架空データ検出テスト"""

    def test_rejects_fabricated_all_pass_snapshot(self, gate, tmp_snapshots):
        """全項目PASS（500超）のスナップショットは拒否される"""
        fabricated = {
            "stories": [
                {
                    "ux_id": f"O-{i}",
                    "verification_items": [
                        {"id": f"O{i}-L{j}-{k:02d}", "passed": True}
                        for j in range(1, 6)
                        for k in range(1, 11)
                    ],
                }
                for i in range(1, 12)
            ]
        }
        # 11 stories × 50 items = 550 items, all passed
        snapshot_path = tmp_snapshots / "v_fabricated.json"
        snapshot_path.write_text(json.dumps(fabricated), encoding="utf-8")

        is_valid, message = gate.verify_snapshot_integrity(snapshot_path)
        assert is_valid is False
        assert "架空データ検出" in message

    def test_accepts_honest_snapshot(self, gate, tmp_snapshots):
        """正直なスナップショット（一部FAIL含む）は受理される"""
        honest = {
            "stories": [
                {
                    "ux_id": "O-1",
                    "verification_items": [
                        {"id": "O1-L1-01", "passed": True},
                        {"id": "O1-L1-02", "passed": False},
                        {"id": "O1-L2-01", "passed": True},
                    ],
                }
            ]
        }
        snapshot_path = tmp_snapshots / "v_honest.json"
        snapshot_path.write_text(json.dumps(honest), encoding="utf-8")

        is_valid, message = gate.verify_snapshot_integrity(snapshot_path)
        assert is_valid is True

    def test_rejects_quarantined_snapshot(self, gate, tmp_snapshots):
        """quarantinedディレクトリ内のスナップショットは拒否される"""
        quarantined_dir = tmp_snapshots / "quarantined"
        quarantined_dir.mkdir()
        snapshot_path = quarantined_dir / "v6.0.json"
        snapshot_path.write_text(json.dumps({"stories": []}), encoding="utf-8")

        is_valid, message = gate.verify_snapshot_integrity(snapshot_path)
        assert is_valid is False
        assert "隔離済み" in message

    def test_accepts_small_all_pass(self, gate, tmp_snapshots):
        """少数項目（500以下）の全PASSは正常として受理"""
        small = {
            "stories": [
                {
                    "ux_id": "O-1",
                    "verification_items": [
                        {"id": f"O1-L1-{i:02d}", "passed": True}
                        for i in range(1, 10)
                    ],
                }
            ]
        }
        snapshot_path = tmp_snapshots / "v_small.json"
        snapshot_path.write_text(json.dumps(small), encoding="utf-8")

        is_valid, message = gate.verify_snapshot_integrity(snapshot_path)
        assert is_valid is True


class TestHarnessIntegrity:
    """ハーネス監査の偽PASS検出テスト"""

    def test_detects_unconditional_true(self, gate):
        """無条件Trueの証拠パターンを検出"""
        is_valid, msg = gate.verify_harness_result(
            "C-01", True, "未実装のためPASS"
        )
        assert is_valid is False
        assert "証拠なしのPASS" in msg

    def test_detects_file_absent_pass(self, gate):
        """ファイル不在でPASSのパターンを検出"""
        is_valid, msg = gate.verify_harness_result(
            "H-04", True, "ファイルなし — ガバナンスチェック動作確認 (PASS)"
        )
        assert is_valid is False

    def test_detects_short_evidence(self, gate):
        """証拠テキストが短すぎる場合を検出"""
        is_valid, msg = gate.verify_harness_result(
            "H-06", True, "OK"
        )
        assert is_valid is False
        assert "不十分" in msg

    def test_accepts_skip(self, gate):
        """SKIP（None）は正直な報告として受理"""
        is_valid, msg = gate.verify_harness_result(
            "C-01", None, "未実装 (SKIP)"
        )
        assert is_valid is True
        assert "SKIP" in msg

    def test_accepts_genuine_pass(self, gate):
        """実質的な証拠のあるPASSは受理"""
        is_valid, msg = gate.verify_harness_result(
            "D-01",
            True,
            "pytest実行完了: 3274 passed, 0 failed. カバレッジ 81.1%",
        )
        assert is_valid is True


class TestUXStoryVerification:
    """UXストーリーPASS主張のe2e_results.json照合テスト"""

    def test_detects_pass_claim_without_result(self, gate):
        """e2e_results.jsonに結果なしだがPASS主張 → 空想リスク"""
        is_valid, msg = gate.verify_ux_story_pass("O-1", "O1-L5-99", True)
        assert is_valid is False
        assert "空想リスク" in msg

    def test_detects_pass_claim_contradicting_fail(self, gate):
        """e2e_results.jsonではFAILだがPASS主張 → 矛盾"""
        is_valid, msg = gate.verify_ux_story_pass("O-1", "O1-L1-02", True)
        assert is_valid is False
        assert "矛盾" in msg

    def test_accepts_consistent_pass(self, gate):
        """e2e_results.jsonと一致するPASS → 整合"""
        is_valid, msg = gate.verify_ux_story_pass("O-1", "O1-L1-01", True)
        assert is_valid is True

    def test_accepts_no_claim_no_result(self, gate):
        """PASS主張なし × 結果なし → 正常（テスト未実行）"""
        is_valid, msg = gate.verify_ux_story_pass("O-1", "O1-L5-99", False)
        assert is_valid is True

    def test_handles_missing_e2e_file(self, tmp_path, tmp_snapshots):
        """e2e_results.jsonが存在しない場合のPASS主張を検出"""
        gate = AntiHallucinationGate(
            snapshots_dir=tmp_snapshots,
            e2e_results_path=tmp_path / "nonexistent.json",
        )
        is_valid, msg = gate.verify_ux_story_pass("O-1", "O1-L1-01", True)
        assert is_valid is False
        assert "不在" in msg


class TestIntegrityReport:
    """整合性レポートの生成テスト"""

    def test_clean_report_has_zero_score(self, gate, tmp_snapshots):
        """違反なしの場合、スコアは0に近い"""
        # 正直なスナップショットのみ配置
        honest = {
            "stories": [
                {
                    "ux_id": "O-1",
                    "verification_items": [
                        {"id": "O1-L1-01", "passed": True},
                        {"id": "O1-L1-02", "passed": False},
                    ],
                }
            ]
        }
        (tmp_snapshots / "v_honest.json").write_text(
            json.dumps(honest), encoding="utf-8"
        )

        report = gate.run_all_checks()
        assert report.hallucination_score < 0.3
        assert report.checks_performed > 0

    def test_report_with_violations(self, gate, tmp_snapshots):
        """違反がある場合、スコアが上昇"""
        # 架空スナップショットを配置
        fabricated = {
            "stories": [
                {
                    "ux_id": f"O-{i}",
                    "verification_items": [
                        {"id": f"O{i}-L{j}-{k:02d}", "passed": True}
                        for j in range(1, 6)
                        for k in range(1, 11)
                    ],
                }
                for i in range(1, 12)
            ]
        }
        (tmp_snapshots / "v_bad.json").write_text(
            json.dumps(fabricated), encoding="utf-8"
        )

        report = gate.run_all_checks()
        assert len(report.violations) > 0
        assert report.hallucination_score > 0

    def test_generate_markdown_report(self, gate):
        """Markdownレポートが生成される"""
        md = gate.generate_integrity_report()
        assert "AntiHallucinationGate" in md
        assert "空想リスクスコア" in md

    def test_empty_checks_max_risk(self):
        """チェック0件の場合、リスクスコアは最大"""
        report = IntegrityReport()
        report.compute_score()
        assert report.hallucination_score == 1.0


class TestAntiHallucinationGateEdgeCases:
    """追加の境界条件や未カバー行を通すためのテスト"""

    def test_integrity_report_is_clean(self):
        # L46: IntegrityReport.is_clean
        report = IntegrityReport()
        assert report.is_clean is True
        
        report.violations.append(IntegrityViolation("snapshot", "HIGH", "desc", "ev"))
        assert report.is_clean is False

    def test_verify_snapshot_integrity_exceptions_and_edge_cases(self, gate, tmp_snapshots):
        # L112-113: json.JSONDecodeError or FileNotFoundError
        bad_json_path = tmp_snapshots / "bad_format.json"
        bad_json_path.write_text("{invalid json", encoding="utf-8")
        is_valid, msg = gate.verify_snapshot_integrity(bad_json_path)
        assert is_valid is False
        assert "スナップショット読込エラー" in msg

        nonexistent_path = tmp_snapshots / "does_not_exist.json"
        is_valid, msg = gate.verify_snapshot_integrity(nonexistent_path)
        assert is_valid is False
        assert "スナップショット読込エラー" in msg

        # L125-129: フラット構造
        flat_data = {
            "story_1": {
                "verification_items": [
                    {"id": "O1-L1-01", "passed": True}
                ]
            }
        }
        flat_path = tmp_snapshots / "flat.json"
        flat_path.write_text(json.dumps(flat_data), encoding="utf-8")
        is_valid, msg = gate.verify_snapshot_integrity(flat_path)
        assert is_valid is True
        assert "正常" in msg

        # L133: total == 0
        empty_data = {"stories": []}
        empty_path = tmp_snapshots / "empty.json"
        empty_path.write_text(json.dumps(empty_data), encoding="utf-8")
        is_valid, msg = gate.verify_snapshot_integrity(empty_path)
        assert is_valid is True
        assert "項目なし" in msg

    def test_verify_ux_story_pass_edge_cases(self, tmp_path, tmp_snapshots):
        # L208: claimed_result is False but e2e_results.json is absent
        gate_no_e2e = AntiHallucinationGate(
            snapshots_dir=tmp_snapshots,
            e2e_results_path=tmp_path / "nonexistent.json",
        )
        is_valid, msg = gate_no_e2e.verify_ux_story_pass("O-1", "O1-L1-01", False)
        assert is_valid is True

        # L213-216: JSONDecodeError on verify_ux_story_pass
        bad_e2e_path = tmp_path / "bad_e2e.json"
        bad_e2e_path.write_text("{invalid json", encoding="utf-8")
        gate_bad_e2e = AntiHallucinationGate(
            snapshots_dir=tmp_snapshots,
            e2e_results_path=bad_e2e_path,
        )
        is_valid, msg = gate_bad_e2e.verify_ux_story_pass("O-1", "O1-L1-01", True)
        assert is_valid is False
        assert "読込エラーでPASS主張" in msg

        is_valid, msg = gate_bad_e2e.verify_ux_story_pass("O-1", "O1-L1-01", False)
        assert is_valid is True
        assert "読込エラー（PASS主張なし）" in msg

    def test_check_snapshot_integrity_nonexistent_dir(self, tmp_path):
        # L245-252: snapshot_dir does not exist
        gate = AntiHallucinationGate(
            snapshots_dir=tmp_path / "nonexistent_snapshots_dir",
        )
        report = IntegrityReport()
        gate._check_snapshot_integrity(report)
        assert len(report.violations) == 1
        assert report.violations[0].source == "snapshot"
        assert report.violations[0].severity == "HIGH"

    def test_check_harness_integrity_decode_error_and_violation(self, gate, tmp_path):
        # L276-288: harness_status_path JSONDecodeError
        bad_harness_path = tmp_path / "bad_harness.json"
        bad_harness_path.write_text("{invalid json", encoding="utf-8")
        gate.harness_status_path = bad_harness_path

        report = IntegrityReport()
        gate._check_harness_integrity(report)
        assert len(report.violations) == 1
        assert "harness_audit_status.json読込エラー" in report.violations[0].description

        # L289-309: Loop with violation detection
        violation_harness_data = {
            "checks": [
                {
                    "id": "C-01",
                    "passed": True,
                    "message": "未実装のためPASS"
                },
                {
                    "id": "C-02",
                    "passed": True,
                    "message": "正常にテストが完了しました。カバレッジも良好です。"
                }
            ]
        }
        violation_harness_path = tmp_path / "violation_harness.json"
        violation_harness_path.write_text(json.dumps(violation_harness_data), encoding="utf-8")
        gate.harness_status_path = violation_harness_path

        report = IntegrityReport()
        gate._check_harness_integrity(report)
        assert len(report.violations) == 1
        assert report.violations[0].severity == "HIGH"
        assert "証拠なしのPASS" in report.violations[0].description
        assert report.checks_passed == 1

    def test_check_e2e_consistency_edge_cases(self, gate, tmp_path):
        # L315-316: e2e_results_path does not exist
        gate.e2e_results_path = tmp_path / "nonexistent_e2e.json"
        report = IntegrityReport()
        gate._check_e2e_consistency(report)
        assert len(report.violations) == 0

        # L321-328: JSONDecodeError on e2e_results.json
        bad_e2e_path = tmp_path / "bad_e2e.json"
        bad_e2e_path.write_text("{invalid json", encoding="utf-8")
        gate.e2e_results_path = bad_e2e_path
        report = IntegrityReport()
        gate._check_e2e_consistency(report)
        assert len(report.violations) == 1
        assert "e2e_results.json読込エラー" in report.violations[0].description

        # L337: total_items == 0
        empty_e2e_path = tmp_path / "empty_e2e.json"
        empty_e2e_path.write_text(json.dumps({"dom_checks": {}}), encoding="utf-8")
        gate.e2e_results_path = empty_e2e_path
        report = IntegrityReport()
        gate._check_e2e_consistency(report)
        assert len(report.violations) == 1
        assert "e2e_results.jsonが空" in report.violations[0].description

    def test_generate_integrity_report_with_violations(self, gate, tmp_snapshots):
        # L362-367: generate_integrity_report with violations
        gate.snapshots_dir = tmp_snapshots / "nonexistent_dir"
        md = gate.generate_integrity_report()
        assert "## 検出された違反" in md
        assert "| 1 | snapshot | HIGH |" in md

    def test_main_execution(self):
        # L378-380, L384: main() function coverage and __main__ block coverage
        import runpy
        from unittest.mock import patch
        with patch("builtins.print") as mock_print:
            import backend.ux_verification.anti_hallucination_gate as gate_mod
            file_path = gate_mod.__file__
            runpy.run_path(file_path, run_name="__main__")
            mock_print.assert_called_once()
