"""
TechnicalDebtStore APIユニットテスト (L2-1)

TDRの全CRUD操作+ラチェット機構+データ保全の動作を
隔離されたtmp_pathで検証する。FF-26(ガバナンス検証)の補完。
"""
import json
import pytest
from pathlib import Path


class TestTechnicalDebtStoreAPI:
    """TDR APIの動作検証（一時ディレクトリで隔離実行）"""

    @pytest.fixture
    def store(self, tmp_path):
        """隔離されたTDRストア（snapshot_dirもtmp_path内）"""
        from agents.memory.technical_debt import TechnicalDebtStore
        s = TechnicalDebtStore(debt_dir=tmp_path)
        # snapshot_dirもtmp_path内に隔離（グローバル参照を防止）
        s.snapshot_dir = tmp_path / "snapshots"
        s.md_path = tmp_path / "TECHNICAL_DEBT_REGISTRY.md"
        return s

    # ========================================================
    # register_debt
    # ========================================================

    def test_register_creates_entry(self, store):
        """register_debtで新しいエントリが作成される"""
        entry = store.register_debt(
            "CRITICAL_ROUTER", "routers/test.py", 10, "except Exception as e:"
        )
        assert entry.debt_id == "TD-001"
        assert entry.status == "open"
        assert entry.category == "CRITICAL_ROUTER"
        assert entry.file_path == "routers/test.py"
        assert entry.line_number == 10
        assert entry.registered_at is not None

    def test_register_auto_increments_id(self, store):
        """IDが自動的にインクリメントされる"""
        e1 = store.register_debt("CRITICAL_ROUTER", "a.py", 1, "except Exception")
        e2 = store.register_debt("CRITICAL_ROUTER", "b.py", 2, "except Exception")
        e3 = store.register_debt("MINOR_INFRA", "c.py", 3, "except Exception")
        assert e1.debt_id == "TD-001"
        assert e2.debt_id == "TD-002"
        assert e3.debt_id == "TD-003"

    def test_register_duplicate_returns_existing(self, store):
        """同一file+lineの重複登録は既存エントリを返す（冪等性）"""
        e1 = store.register_debt("CRITICAL_ROUTER", "test.py", 10, "except Exception")
        e2 = store.register_debt("CRITICAL_ROUTER", "test.py", 10, "except Exception")
        assert e1.debt_id == e2.debt_id
        assert len(store.entries) == 1

    def test_register_invalid_category_raises(self, store):
        """無効なカテゴリでValueError"""
        with pytest.raises(ValueError, match="Invalid category"):
            store.register_debt("INVALID_CAT", "test.py", 10, "except Exception")

    def test_register_with_all_optional_fields(self, store):
        """全オプションフィールドを指定して登録"""
        entry = store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="services/test.py",
            line_number=50,
            pattern="except Exception as e:",
            cause_pattern="DP-02",
            fix_pattern="except HTTPException: raise を追加",
            registered_by="sprint_test",
            notes="テスト用ノート",
            tags=["router", "guard"],
        )
        assert entry.cause_pattern == "DP-02"
        assert entry.fix_pattern == "except HTTPException: raise を追加"
        assert entry.registered_by == "sprint_test"
        assert entry.notes == "テスト用ノート"
        assert entry.tags == ["router", "guard"]

    # ========================================================
    # resolve_debt
    # ========================================================

    def test_resolve_sets_fixed_with_evidence(self, store):
        """resolve_debtで証拠付きfixed"""
        store.register_debt("CRITICAL_ROUTER", "test.py", 10, "except Exception")
        result = store.resolve_debt("TD-001", "sprint_x", "pytest 3050 passed")
        assert result.status == "fixed"
        assert result.fixed_by == "sprint_x"
        assert result.fix_evidence == "pytest 3050 passed"
        assert result.fixed_at is not None

    def test_resolve_already_fixed_returns_entry(self, store):
        """既にfixedのエントリへのresolveは既存を返す"""
        store.register_debt("CRITICAL_ROUTER", "test.py", 10, "except Exception")
        store.resolve_debt("TD-001", "sprint_a", "evidence_a")
        result = store.resolve_debt("TD-001", "sprint_b", "evidence_b")
        assert result.status == "fixed"
        # 最初のfixが保持される（上書きされない）
        assert result.fixed_by == "sprint_a"

    def test_resolve_nonexistent_returns_none(self, store):
        """存在しないIDへのresolveはNone"""
        result = store.resolve_debt("TD-999", "sprint_x", "evidence")
        assert result is None

    # ========================================================
    # accept_debt — P3保全チェック
    # ========================================================

    def test_accept_preserves_existing_notes(self, store):
        """accept_debtが既存notesを保全する（P3修正）"""
        store.register_debt(
            "MINOR_INFRA", "test.py", 10, "except Exception",
            notes="初回登録メモ"
        )
        store.accept_debt("TD-001", "正当な安全ネット: ログ出力用")
        entry = store.get_entry("TD-001")
        assert entry.status == "accepted"
        assert "初回登録メモ" in entry.notes  # 既存notes保全
        assert "正当な安全ネット" in entry.notes  # 新理由も追記
        assert entry.fixed_at is not None

    def test_accept_with_empty_notes(self, store):
        """notesが空の場合もacceptが正常動作"""
        store.register_debt("MINOR_INFRA", "test.py", 10, "except Exception")
        store.accept_debt("TD-001", "safety net")
        entry = store.get_entry("TD-001")
        assert "safety net" in entry.notes

    # ========================================================
    # reopen_debt — P5保全チェック
    # ========================================================

    def test_reopen_preserves_fix_history(self, store):
        """reopen_debtが旧修正情報をnotesに保全する（P5修正）"""
        store.register_debt("CRITICAL_ROUTER", "test.py", 10, "except Exception")
        store.resolve_debt("TD-001", "sprint_a", "evidence_a: pytest passed")
        store.reopen_debt("TD-001", "回帰バグ発見")
        entry = store.get_entry("TD-001")
        assert entry.status == "open"
        assert entry.fixed_at is None  # リセット済み
        assert entry.fixed_by is None
        assert entry.fix_evidence is None
        # 旧情報がnotesに保全
        assert "sprint_a" in entry.notes
        assert "evidence_a" in entry.notes
        assert "回帰バグ発見" in entry.notes

    def test_reopen_multiple_cycles(self, store):
        """fix→reopen→fix→reopen の複数サイクルで全履歴が蓄積"""
        store.register_debt("CRITICAL_ROUTER", "test.py", 10, "except Exception")

        # Cycle 1
        store.resolve_debt("TD-001", "sprint_1", "evidence_1")
        store.reopen_debt("TD-001", "regression_1")

        # Cycle 2
        store.resolve_debt("TD-001", "sprint_2", "evidence_2")
        store.reopen_debt("TD-001", "regression_2")

        entry = store.get_entry("TD-001")
        assert "sprint_1" in entry.notes
        assert "evidence_1" in entry.notes
        assert "sprint_2" in entry.notes
        assert "evidence_2" in entry.notes

    # ========================================================
    # クエリ系
    # ========================================================

    def test_get_entries_by_file(self, store):
        """ファイル別エントリ取得"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("CRITICAL_ROUTER", "a.py", 20, "except Exception")
        store.register_debt("MINOR_INFRA", "b.py", 30, "except Exception")
        results = store.get_entries_by_file("a.py")
        assert len(results) == 2

    def test_get_entries_by_category(self, store):
        """カテゴリ別エントリ取得"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("MINOR_INFRA", "b.py", 20, "except Exception")
        results = store.get_entries_by_category("CRITICAL_ROUTER")
        assert len(results) == 1

    def test_get_open_entries(self, store):
        """openエントリのみ取得"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("MINOR_INFRA", "b.py", 20, "except Exception")
        store.resolve_debt("TD-001", "sprint", "evidence")
        results = store.get_open_entries()
        assert len(results) == 1
        assert results[0].debt_id == "TD-002"

    def test_get_critical_open_count(self, store):
        """CRITICALのopen件数"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("CRITICAL_PHASE4", "b.py", 20, "except Exception")
        store.register_debt("MINOR_INFRA", "c.py", 30, "except Exception")
        assert store.get_critical_open_count() == 2
        store.resolve_debt("TD-001", "sprint", "evidence")
        assert store.get_critical_open_count() == 1

    # ========================================================
    # サマリー・コンテキスト
    # ========================================================

    def test_get_summary(self, store):
        """サマリーが正しい統計を返す"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("MINOR_INFRA", "b.py", 20, "except Exception")
        store.resolve_debt("TD-001", "sprint", "evidence")
        summary = store.get_summary()
        assert summary["total"] == 2
        assert summary["by_status"]["fixed"] == 1
        assert summary["by_status"]["open"] == 1
        assert summary["critical_open"] == 0

    def test_get_context_for_file(self, store):
        """ファイルコンテキストがMarkdown形式で出力"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        ctx = store.get_context_for_file("a.py")
        assert "a.py" in ctx
        assert "TD-001" in ctx
        assert "🔴" in ctx  # openアイコン

    def test_get_context_for_unknown_file(self, store):
        """未登録ファイルのコンテキストは空文字"""
        assert store.get_context_for_file("nonexistent.py") == ""

    # ========================================================
    # ラチェット
    # ========================================================

    def test_ratchet_passes_on_decrease(self, store):
        """CRITICAL open減少時はラチェットPASS"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("CRITICAL_ROUTER", "b.py", 20, "except Exception")
        store.create_snapshot("1.0")  # critical_open=2
        store.resolve_debt("TD-001", "sprint", "evidence")
        ratchet = store.check_ratchet()
        assert ratchet["passed"] is True
        assert ratchet["delta"] == -1

    def test_ratchet_fails_on_increase(self, store):
        """CRITICAL open増加時はラチェットFAIL"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.create_snapshot("1.0")  # critical_open=1
        store.register_debt("CRITICAL_ROUTER", "b.py", 20, "except Exception")
        ratchet = store.check_ratchet()
        assert ratchet["passed"] is False
        assert ratchet["delta"] == 1

    def test_ratchet_first_run_passes(self, store):
        """スナップショットなしの初回はPASS"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        ratchet = store.check_ratchet()
        assert ratchet["passed"] is True
        assert ratchet["previous"] is None

    # ========================================================
    # 永続化
    # ========================================================

    def test_json_persistence(self, store, tmp_path):
        """JSONファイルへの永続化と復元"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.resolve_debt("TD-001", "sprint", "evidence")
        store.register_debt("MINOR_INFRA", "b.py", 20, "except Exception")

        # 別インスタンスからロード
        from agents.memory.technical_debt import TechnicalDebtStore
        store2 = TechnicalDebtStore(debt_dir=tmp_path)
        assert len(store2.entries) == 2
        assert store2.entries[0].status == "fixed"
        assert store2.entries[1].status == "open"

    def test_stats(self, store):
        """統計情報の正確性"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("MINOR_INFRA", "b.py", 20, "except Exception")
        stats = store.get_stats()
        assert stats["total_entries"] == 2
        assert stats["by_status"]["open"] == 2
        assert stats["critical_open"] == 1

    # ========================================================
    # スキーマ進化 (C1ガード)
    # ========================================================

    def test_load_ignores_unknown_fields(self, store, tmp_path):
        """JSONに未知フィールドがあってもロード成功"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store._save()

        # 未知フィールドを直接追加
        json_path = tmp_path / "technical_debt_index.json"
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["entries"][0]["future_field"] = "future_value"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        from agents.memory.technical_debt import TechnicalDebtStore
        store2 = TechnicalDebtStore(debt_dir=tmp_path)
        store2.snapshot_dir = tmp_path / "snapshots"
        assert len(store2.entries) == 1
        assert not hasattr(store2.entries[0], "future_field")

    def test_load_fills_missing_optional_fields(self, store, tmp_path):
        """JSONから任意フィールド(notes, tags)が欠損してもdefaultで補完"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store._save()

        # notes と tags を削除
        json_path = tmp_path / "technical_debt_index.json"
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        del data["entries"][0]["notes"]
        del data["entries"][0]["tags"]
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        from agents.memory.technical_debt import TechnicalDebtStore
        store2 = TechnicalDebtStore(debt_dir=tmp_path)
        store2.snapshot_dir = tmp_path / "snapshots"
        assert len(store2.entries) == 1
        assert store2.entries[0].notes == ""  # default value
        assert store2.entries[0].tags == []   # default_factory value

    # ========================================================
    # changelog
    # ========================================================

    def test_changelog_records_all_actions(self, store):
        """changelogが全CRUD操作を記録する"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.resolve_debt("TD-001", "sprint_1", "evidence_1")
        store.reopen_debt("TD-001", "regression")
        store.accept_debt("TD-001", "safety net")

        log = store.get_changelog("TD-001")
        assert len(log) == 4
        assert [r.action for r in log] == ["registered", "resolved", "reopened", "accepted"]

    def test_changelog_persists(self, store, tmp_path):
        """changelogがJSON永続化+ロード復元される"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.resolve_debt("TD-001", "sprint_1", "evidence_1")
        store._save()

        from agents.memory.technical_debt import TechnicalDebtStore
        store2 = TechnicalDebtStore(debt_dir=tmp_path)
        store2.snapshot_dir = tmp_path / "snapshots"
        log = store2.get_changelog("TD-001")
        assert len(log) == 2
        assert log[0].action == "registered"
        assert log[1].action == "resolved"

    # ========================================================
    # L5-1: verify_debt — 最終検証日
    # ========================================================

    def test_verify_updates_last_verified_at(self, store):
        """verify_debtがlast_verified_atを更新する"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        assert store.entries[0].last_verified_at is None
        result = store.verify_debt("TD-001")
        assert result is not None
        assert result.last_verified_at is not None
        assert "T" in result.last_verified_at  # ISO8601形式

    def test_verify_nonexistent_returns_none(self, store):
        """存在しないIDへのverifyはNone"""
        assert store.verify_debt("TD-999") is None

    def test_verify_adds_changelog(self, store):
        """verify_debtがchangelogにverifiedアクションを記録する"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.verify_debt("TD-001")
        log = store.get_changelog("TD-001")
        assert any(r.action == "verified" for r in log)

    # ========================================================
    # L5-5: confidence
    # ========================================================

    def test_confidence_default_is_1(self, store):
        """confidenceのデフォルト値は1.0"""
        entry = store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        assert entry.confidence == 1.0

    def test_confidence_persists(self, store, tmp_path):
        """confidence値がJSON永続化・復元される"""
        entry = store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        entry.confidence = 0.7
        store._save()

        from agents.memory.technical_debt import TechnicalDebtStore
        store2 = TechnicalDebtStore(debt_dir=tmp_path)
        store2.snapshot_dir = tmp_path / "snapshots"
        assert store2.entries[0].confidence == 0.7

    # ========================================================
    # L6-1: estimated_fix_minutes / get_cost_summary
    # ========================================================

    def test_estimated_fix_minutes_default_none(self, store):
        """estimated_fix_minutesのデフォルトはNone"""
        entry = store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        assert entry.estimated_fix_minutes is None

    def test_get_cost_summary(self, store):
        """get_cost_summaryがカテゴリ別コストを正しく算出"""
        e1 = store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        e1.estimated_fix_minutes = 30
        e2 = store.register_debt("CRITICAL_ROUTER", "b.py", 20, "except Exception")
        e2.estimated_fix_minutes = 60
        e3 = store.register_debt("MINOR_INFRA", "c.py", 30, "except Exception")
        # e3 has no estimate
        cost = store.get_cost_summary()
        assert cost["by_category"]["CRITICAL_ROUTER"] == 90
        assert cost["total_minutes"] == 90
        assert cost["total_hours"] == 1.5
        assert cost["unestimated_count"] == 1

    # ========================================================
    # L5-4: get_contradictions
    # ========================================================

    def test_get_contradictions_empty_when_clean(self, store):
        """矛盾がない場合は空リスト"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("MINOR_INFRA", "b.py", 20, "except Exception")
        assert store.get_contradictions() == []

    def test_get_contradictions_detects_duplicate_location(self, store):
        """同一location・異なるカテゴリの矛盾を検出"""
        # 重複チェックを回避するため直接エントリを追加
        from agents.memory.technical_debt import TechnicalDebtEntry
        from datetime import datetime
        now = datetime.now().isoformat()
        store.entries.append(TechnicalDebtEntry(
            debt_id="TD-001", category="CRITICAL_ROUTER", file_path="a.py",
            line_number=10, pattern="except Exception", cause_pattern="",
            fix_pattern="", status="open", registered_at=now, registered_by="test"
        ))
        store.entries.append(TechnicalDebtEntry(
            debt_id="TD-002", category="MINOR_INFRA", file_path="a.py",
            line_number=10, pattern="except Exception", cause_pattern="",
            fix_pattern="", status="open", registered_at=now, registered_by="test"
        ))
        contradictions = store.get_contradictions()
        assert len(contradictions) == 1
        assert "a.py:L10" in contradictions[0]["location"]

    # ========================================================
    # L5-2: _enforce_limits
    # ========================================================

    def test_enforce_limits_under_max(self, store):
        """上限以下ではエントリが削除されない"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store._enforce_limits()
        assert len(store.entries) == 1

    def test_enforce_limits_removes_oldest_fixed(self, store):
        """上限超過時に最古のfixed/acceptedが削除される"""
        store.MAX_ENTRIES = 3  # テスト用に小さい値
        store.register_debt("CRITICAL_ROUTER", "a.py", 1, "except Exception")
        store.register_debt("CRITICAL_ROUTER", "b.py", 2, "except Exception")
        store.resolve_debt("TD-001", "sprint", "evidence")  # fixedに
        store.register_debt("MINOR_INFRA", "c.py", 3, "except Exception")
        store.register_debt("MINOR_INFRA", "d.py", 4, "except Exception")
        # 4件 > MAX_ENTRIES=3 → TD-001(fixed)が削除される
        assert len(store.entries) == 3
        assert all(e.debt_id != "TD-001" for e in store.entries)

    # ========================================================
    # L5-3: get_entries_for_context
    # ========================================================

    def test_get_entries_for_context_priority_order(self, store):
        """CRITICAL > IMPORTANT > MINORの優先度で返却"""
        store.register_debt("MINOR_INFRA", "c.py", 30, "except Exception")
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store.register_debt("IMPORTANT_SERVICE", "b.py", 20, "except Exception")
        result = store.get_entries_for_context(max_entries=10)
        assert len(result) == 3
        assert result[0].category == "CRITICAL_ROUTER"
        assert result[1].category == "IMPORTANT_SERVICE"
        assert result[2].category == "MINOR_INFRA"

    def test_get_entries_for_context_respects_limit(self, store):
        """max_entriesで件数制限"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 1, "except Exception")
        store.register_debt("CRITICAL_ROUTER", "b.py", 2, "except Exception")
        store.register_debt("CRITICAL_ROUTER", "c.py", 3, "except Exception")
        result = store.get_entries_for_context(max_entries=2)
        assert len(result) == 2

    # ========================================================
    # L6-3: get_pattern_analysis
    # ========================================================

    def test_get_pattern_analysis(self, store):
        """cause_pattern別の分析が正しく動作"""
        for i in range(12):
            e = store.register_debt(
                "MINOR_INFRA", f"f{i}.py", i + 1, "except Exception",
                cause_pattern="DP-01"
            )
        store.register_debt(
            "MINOR_INFRA", "g.py", 100, "except Exception",
            cause_pattern="DP-02"
        )
        analysis = store.get_pattern_analysis()
        assert "DP-01" in analysis["by_pattern"]
        assert analysis["by_pattern"]["DP-01"]["total"] == 12
        assert "DP-01" in analysis["recurring_patterns"]
        assert "DP-02" not in analysis["recurring_patterns"]
        assert "繰り返し" in analysis["recommendation"]

    # ========================================================
    # 新フィールドのスキーマ進化互換性
    # ========================================================

    def test_new_fields_backward_compatible(self, store, tmp_path):
        """新フィールド(last_verified_at, confidence, estimated_fix_minutes)が
        欠損JSONからもdefaultで安全にロードされる"""
        store.register_debt("CRITICAL_ROUTER", "a.py", 10, "except Exception")
        store._save()

        # 新フィールドをJSONから手動削除（旧バージョンのJSONをシミュレート）
        json_path = tmp_path / "technical_debt_index.json"
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for field_name in ["last_verified_at", "confidence", "estimated_fix_minutes"]:
            if field_name in data["entries"][0]:
                del data["entries"][0][field_name]
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 再ロードしてdefault値が補完されるか
        from agents.memory.technical_debt import TechnicalDebtStore
        store2 = TechnicalDebtStore(debt_dir=tmp_path)
        store2.snapshot_dir = tmp_path / "snapshots"
        assert len(store2.entries) == 1
        assert store2.entries[0].last_verified_at is None
        assert store2.entries[0].confidence == 1.0
        assert store2.entries[0].estimated_fix_minutes is None
