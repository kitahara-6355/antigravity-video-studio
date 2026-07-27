"""TaskLearningEngine のテスト"""
import os
import sys
import json
import pytest
from pathlib import Path

# 動的パス解決
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agents.orchestration.task_learning_engine import TaskLearningEngine


@pytest.fixture
def sample_reports(tmp_path):
    """テスト用のflash_reports.jsonlを作成"""
    reports_path = tmp_path / "flash_reports.jsonl"
    reports = []

    # 3バッチ分のデータを生成
    for batch_idx in range(3):
        batch_id = f"batch_test_{batch_idx:03d}"
        tasks = []
        # test_weaver: 2タスク (1 hit, 1 miss)
        tasks.append({
            "id": f"T-{batch_id}-tw-000",
            "group": "test_weaver",
            "target_module": "services/encoder.py",
            "status": "pass",
            "result": {
                "changed_files": ["tests/test_encoder.py"] if batch_idx % 2 == 0 else [],
                "message": "test added" if batch_idx % 2 == 0 else "no uncovered lines",
            },
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:05:00+00:00",
        })
        tasks.append({
            "id": f"T-{batch_id}-tw-001",
            "group": "test_weaver",
            "target_module": "services/decoder.py",
            "status": "pass",
            "result": {
                "changed_files": ["tests/test_decoder.py"],
                "message": "test added",
            },
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:03:00+00:00",
        })
        # bug_hunter: 1タスク (always hit)
        tasks.append({
            "id": f"T-{batch_id}-bh-000",
            "group": "bug_hunter",
            "target_module": "services/encoder.py",
            "status": "pass",
            "result": {
                "changed_files": ["services/encoder.py", "tests/test_encoder.py"],
                "message": "bug fixed",
            },
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:10:00+00:00",
        })
        # refactor: 1タスク (always hit)
        tasks.append({
            "id": f"T-{batch_id}-rf-000",
            "group": "refactor",
            "target_module": "services/encoder.py",
            "status": "pass",
            "result": {
                "changed_files": ["services/encoder.py"],
                "message": "refactored",
            },
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:02:00+00:00",
        })

        reports.append({
            "batch_id": batch_id,
            "timestamp": f"2026-01-0{batch_idx+1}T00:00:00+00:00",
            "tasks": tasks,
        })

    with open(reports_path, "w", encoding="utf-8") as f:
        for r in reports:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return reports_path


@pytest.fixture
def engine(sample_reports, tmp_path):
    return TaskLearningEngine(
        reports_path=sample_reports,
        cache_path=tmp_path / "cache.json",
    )


class TestTaskLearningEngine:

    def test_group_performance_report(self, engine):
        """グループ別パフォーマンスが正しく計算される"""
        report = engine.get_group_performance_report()
        assert "test_weaver" in report
        assert "bug_hunter" in report
        assert "refactor" in report
        # bug_hunter は全ヒット
        assert report["bug_hunter"]["hit_rate"] == 1.0
        assert report["bug_hunter"]["total"] == 3
        # refactor も全ヒット
        assert report["refactor"]["hit_rate"] == 1.0
        # test_weaver は部分ヒット
        assert 0 < report["test_weaver"]["hit_rate"] < 1.0

    def test_module_group_affinity(self, engine):
        """モジュール×グループの親和性が計算される"""
        affinity = engine.get_module_group_affinity(top_n=5)
        assert len(affinity) > 0
        for item in affinity:
            assert "module" in item
            assert "best_group" in item
            assert "hit_rate" in item
            assert 0 <= item["hit_rate"] <= 1.0

    def test_optimal_batch_composition(self, engine):
        """バッチ配分が正しく計算される"""
        comp = engine.suggest_optimal_batch_composition(batch_size=12)
        assert sum(comp.values()) == 12
        assert all(v >= 1 for v in comp.values())

    def test_optimal_batch_composition_sum(self, engine):
        """バッチサイズが正確に合計される"""
        for size in [6, 10, 15]:
            comp = engine.suggest_optimal_batch_composition(batch_size=size)
            assert sum(comp.values()) == size

    def test_suggest_module_for_group(self, engine):
        """グループに最適なモジュールが推薦される"""
        modules = ["services/encoder.py", "services/decoder.py", "services/other.py"]
        suggested = engine.suggest_module_for_group("bug_hunter", modules)
        assert suggested in modules

    def test_suggest_module_with_exclude(self, engine):
        """除外リストが機能する"""
        modules = ["services/encoder.py", "services/decoder.py"]
        suggested = engine.suggest_module_for_group(
            "bug_hunter", modules, exclude={"services/encoder.py"}
        )
        assert suggested == "services/decoder.py"

    def test_get_summary(self, engine):
        """サマリーが正常に生成される"""
        summary = engine.get_summary()
        assert "グループ別有効打率" in summary
        assert "推奨バッチ配分" in summary

    def test_save_cache(self, engine, tmp_path):
        """キャッシュが保存される"""
        engine.save_cache()
        cache_path = tmp_path / "cache.json"
        assert cache_path.exists()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "group_performance" in data
        assert "optimal_composition_12" in data

    def test_empty_reports(self, tmp_path):
        """空のレポートでもエラーなし"""
        empty_path = tmp_path / "empty.jsonl"
        empty_path.write_text("", encoding="utf-8")
        engine = TaskLearningEngine(
            reports_path=empty_path,
            cache_path=tmp_path / "cache.json",
        )
        report = engine.get_group_performance_report()
        assert report == {}
        comp = engine.suggest_optimal_batch_composition(12)
        assert sum(comp.values()) == 12
        
        # AttributeErrorが発生しないことを検証
        diminishing = engine.detect_diminishing_returns()
        assert diminishing == []
        
        # save_cacheが正常終了することを検証
        engine.save_cache()
        cache_path = tmp_path / "cache.json"
        assert cache_path.exists()

    def test_invalid_reports(self, tmp_path):
        """不正なデータ構造のレポートでもエラーなし"""
        invalid_path = tmp_path / "invalid.jsonl"
        reports = [
            # 1. tasksがリストではない
            {"batch_id": "batch_invalid_1", "tasks": None},
            # 2. task内のresultが辞書ではない、またはchanged_filesがリストではない
            {
                "batch_id": "batch_invalid_2",
                "tasks": [
                    {
                        "group": "bug_hunter",
                        "target_module": "services/encoder.py",
                        "result": None,
                    },
                    {
                        "group": "refactor",
                        "target_module": "services/decoder.py",
                        "result": {
                            "changed_files": "not_a_list",
                        }
                    }
                ]
            },
            # 3. report自体が辞書ではない
            "not_a_dictionary_at_all"
        ]
        with open(invalid_path, "w", encoding="utf-8") as f:
            for r in reports:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        engine = TaskLearningEngine(
            reports_path=invalid_path,
            cache_path=tmp_path / "cache.json",
        )
        
        # エラーを発生させずに分析を完了できることを確認
        report = engine.get_group_performance_report()
        # bug_hunterとrefactorは共にchanged_filesがリストでない、またはNoneなのでhitにならないはず
        assert "bug_hunter" in report
        assert report["bug_hunter"]["total"] == 1
        assert report["bug_hunter"]["hits"] == 0
        
        assert "refactor" in report
        assert report["refactor"]["total"] == 1
        assert report["refactor"]["hits"] == 0
        
        diminishing = engine.detect_diminishing_returns()
        assert isinstance(diminishing, list)
        
        engine.save_cache()

    def test_detect_diminishing_returns(self, engine):
        """収穫逓減検出が動作する（サンプル数不足でも空リスト返却）"""
        result = engine.detect_diminishing_returns()
        assert isinstance(result, list)

    def test_detect_diminishing_returns_with_data(self, tmp_path):
        """6回以上のタスクがあり、変更ファイル数が減少しているモジュールの収穫逓減が正しく検出される"""
        reports_path = tmp_path / "diminishing_reports.jsonl"
        reports = []
        
        # 6バッチ分。services/encoder.py の変更ファイル数が 10, 8, 6, 2, 1, 0 と減少する
        changed_counts = [10, 8, 6, 2, 1, 0]
        for idx, count in enumerate(changed_counts):
            batch_id = f"batch_dim_{idx}"
            tasks = [{
                "id": f"T-{batch_id}-tw-000",
                "group": "test_weaver",
                "target_module": "services/encoder.py",
                "status": "pass",
                "result": {
                    "changed_files": ["file.py"] * count,
                },
                "started_at": "2026-01-01T00:00:00+00:00",
                "completed_at": "2026-01-01T00:05:00+00:00",
            }]
            reports.append({
                "batch_id": batch_id,
                "tasks": tasks
            })
            
        with open(reports_path, "w", encoding="utf-8") as f:
            for r in reports:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                
        engine = TaskLearningEngine(
            reports_path=reports_path,
            cache_path=tmp_path / "cache.json",
        )
        
        # 減少率のしきい値 0.3 (30%) で検出されるはず
        diminishing = engine.detect_diminishing_returns(threshold=0.3)
        assert len(diminishing) == 1
        assert diminishing[0]["module"] == "services/encoder.py"
        assert diminishing[0]["trend"] == "declining"
        assert diminishing[0]["decline_rate"] > 0.3
        
        # しきい値 0.99 などの極端に高い値では検出されないはず
        diminishing_strict = engine.detect_diminishing_returns(threshold=0.99)
        assert len(diminishing_strict) == 0

    def test_suggest_module_for_group_edge_cases(self, engine):
        """suggest_module_for_group のエッジケース（空の候補、全除外など）で None が返される"""
        # 1. available_modules が空の場合
        assert engine.suggest_module_for_group("bug_hunter", []) is None
        
        # 2. すべての候補が exclude されている場合
        modules = ["services/encoder.py", "services/decoder.py"]
        assert engine.suggest_module_for_group("bug_hunter", modules, exclude=set(modules)) is None

    def test_optimal_batch_composition_guarantees_minimum_one_slot(self, tmp_path):
        """打率0のグループや低打率のグループが含まれていても、すべてのグループに最低1スロットが割り当てられる"""
        reports_path = tmp_path / "zero_hit_reports.jsonl"
        reports = []
        
        # 5つのグループを用意。
        # tw (test_weaver): 5 total, 5 hits (1.0)
        # bh (bug_hunter): 5 total, 3 hits (0.6)
        # rf (refactor): 5 total, 1 hit (0.2)
        # tdr (tdr_cleanup): 5 total, 0 hits (0.0)
        # th (thumbnail): 5 total, 0 hits (0.0)
        groups = {
            "test_weaver": {"total": 5, "hits": 5},
            "bug_hunter": {"total": 5, "hits": 3},
            "refactor": {"total": 5, "hits": 1},
            "tdr_cleanup": {"total": 5, "hits": 0},
            "thumbnail": {"total": 5, "hits": 0}
        }
        
        for batch_idx in range(5):
            batch_id = f"batch_test_{batch_idx:03d}"
            tasks = []
            for gname, stats in groups.items():
                is_hit = batch_idx < stats["hits"]
                tasks.append({
                    "id": f"T-{batch_id}-{gname}",
                    "group": gname,
                    "target_module": "services/encoder.py",
                    "status": "pass",
                    "result": {
                        "changed_files": ["services/encoder.py"] if is_hit else [],
                    }
                })
            reports.append({
                "batch_id": batch_id,
                "tasks": tasks
            })
            
        with open(reports_path, "w", encoding="utf-8") as f:
            for r in reports:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                
        engine = TaskLearningEngine(
            reports_path=reports_path,
            cache_path=tmp_path / "cache.json",
        )
        
        # バッチサイズ 12。グループ数が 5。
        # 全グループに最低1スロット割り当てられるはずなので、すべてのグループでスロット数が >= 1 となる。
        comp = engine.suggest_optimal_batch_composition(batch_size=12)
        assert sum(comp.values()) == 12
        for gname in groups.keys():
            assert gname in comp
            assert comp[gname] >= 1, f"Group {gname} got {comp[gname]} slots, expected at least 1"

    def test_save_cache_type_error(self, engine, monkeypatch):
        """save_cache で TypeError が発生した場合に正しく warning が記録され再送される"""
        from unittest.mock import MagicMock
        
        # _write_json が TypeError を発生させるように mock
        mock_write = MagicMock(side_effect=TypeError("Mock serialisation error"))
        monkeypatch.setattr("backend.agents.orchestration.task_learning_engine._write_json", mock_write)
        
        with pytest.raises(TypeError, match="Mock serialisation error"):
            engine.save_cache()

    def test_save_cache_os_error(self, engine, monkeypatch):
        """save_cache で OSError が発生した場合に正しく warning が記録され再送される"""
        from unittest.mock import MagicMock
        
        # _write_json が OSError を発生させるように mock
        mock_write = MagicMock(side_effect=OSError("Mock OS write error"))
        monkeypatch.setattr("backend.agents.orchestration.task_learning_engine._write_json", mock_write)
        
        with pytest.raises(OSError, match="Mock OS write error"):
            engine.save_cache()
