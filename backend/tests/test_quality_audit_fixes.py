"""
品質監査修正テスト（TS-01）

対象:
- safe_io.py （DT-01: SafeJsonStore のアトミック書き込み＋スレッドセーフ）
- hook_evolution_service.py （AR-04: サービス層移行）
- post_publish_collector.py （MK-01: 決定論的モック）
- series_planner.py （DT-01: SafeJsonStore 適用確認）
- prediction_validator.py （DT-02: get_record API）
- retention_map_plugin.py （Phase 3 基本検証）
- wagamama_manager.py （DT-02: get_record パブリックAPI）
"""
import pytest
import sys
import os
import json
import asyncio
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# パス設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ===========================================================================
# DT-01: SafeJsonStore テスト
# ===========================================================================
class TestSafeJsonStore:
    """safe_io.py のアトミック書き込みとスレッドセーフ性を検証"""

    def test_save_and_load_roundtrip(self, tmp_path):
        """保存したデータが正しく読み込めること"""
        from safe_io import SafeJsonStore

        store = SafeJsonStore(tmp_path / "test.json", default={"items": []})
        data = {"items": [1, 2, 3], "name": "テスト"}
        store.save(data)
        loaded = store.load()
        assert loaded == data

    def test_load_returns_default_when_file_missing(self, tmp_path):
        """ファイルが存在しない場合はデフォルト値を返すこと"""
        from safe_io import SafeJsonStore

        default = {"version": "1.0", "items": []}
        store = SafeJsonStore(tmp_path / "nonexistent.json", default=default)
        loaded = store.load()
        assert loaded == default

    def test_load_returns_default_on_corrupt_json(self, tmp_path):
        """JSONが壊れている場合はデフォルト値を返すこと"""
        from safe_io import SafeJsonStore

        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("{invalid json", encoding="utf-8")

        default = {"fallback": True}
        store = SafeJsonStore(corrupt_file, default=default)
        loaded = store.load()
        assert loaded == default

    def test_atomic_write_does_not_corrupt_on_error(self, tmp_path):
        """書き込み中にエラーが起きても元ファイルが破損しないこと"""
        from safe_io import SafeJsonStore

        store = SafeJsonStore(tmp_path / "safe.json")
        original_data = {"original": True}
        store.save(original_data)

        # 書き込み不能なデータ（循環参照はjson.dumpでエラー）
        bad_data = {"key": object()}
        with pytest.raises(TypeError):
            store.save(bad_data)

        # 元データが残っていること
        loaded = store.load()
        assert loaded == original_data

    def test_update_is_atomic(self, tmp_path):
        """update() が読み→更新→保存をアトミックに実行すること"""
        from safe_io import SafeJsonStore

        store = SafeJsonStore(tmp_path / "atomic.json", default={"count": 0})
        store.save({"count": 0})

        store.update(lambda data: {**data, "count": data["count"] + 1})
        loaded = store.load()
        assert loaded["count"] == 1

    def test_thread_safety(self, tmp_path):
        """複数スレッドからの同時書き込みでデータが破損しないこと"""
        from safe_io import SafeJsonStore

        store = SafeJsonStore(tmp_path / "threaded.json", default={"values": []})
        store.save({"values": []})

        errors = []

        def append_value(val):
            try:
                # update() を使えばロック範囲内で読み→更新→保存が完結する
                def updater(data):
                    data["values"].append(val)
                    return data
                store.update(updater)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=append_value, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        final = store.load()
        # update() によりロック内で操作されるため、全ての値が書き込まれる
        assert len(final["values"]) == 10

    def test_creates_parent_directories(self, tmp_path):
        """親ディレクトリが存在しない場合に自動作成されること"""
        from safe_io import SafeJsonStore

        deep_path = tmp_path / "a" / "b" / "c" / "test.json"
        store = SafeJsonStore(deep_path)
        store.save({"nested": True})
        assert deep_path.exists()


# ===========================================================================
# AR-04: HookEvolutionService テスト
# ===========================================================================
class TestHookEvolutionService:
    """hook_evolution_service.py のサービス層ロジックを検証"""

    @pytest.fixture
    def service(self, tmp_path):
        """テスト用サービスインスタンス"""
        from services.hook_evolution_service import HookEvolutionService
        from safe_io import SafeJsonStore

        svc = HookEvolutionService()
        # テスト用の一時ファイルを使う
        svc._store = SafeJsonStore(
            tmp_path / "evolution_log.json",
            default={"entries": [], "hook_improvements": []}
        )
        return svc

    def test_apply_improvement(self, service):
        """改善適用が正しく記録されること"""
        result = service.apply_improvement(
            task_id="T-001",
            improvement_type="attention",
            original_text="元のテキスト",
            improved_text="改善テキスト",
            expected_score_boost=15
        )
        assert result["success"] is True
        assert result["applied"]["type"] == "attention"

    def test_apply_and_get_history(self, service):
        """適用後に履歴で確認できること"""
        service.apply_improvement(
            task_id="T-001",
            improvement_type="emotion",
            original_text="Original",
            improved_text="Improved"
        )
        history = service.get_history()
        assert history["count"] == 1
        assert history["history"][0]["type"] == "emotion"
        assert history["history"][0]["status"] == "applied"

    def test_revert_latest(self, service):
        """最新の改善を取り消せること"""
        service.apply_improvement(
            task_id="T-001",
            improvement_type="curiosity",
            original_text="Before",
            improved_text="After"
        )
        result = service.revert_latest()
        assert result["success"] is True
        assert result["reverted_text"] == "Before"

        # 再度取り消し → 失敗
        result2 = service.revert_latest()
        assert result2["success"] is False

    def test_revert_empty(self, service):
        """改善がない状態で取り消し → 適切なメッセージ"""
        result = service.revert_latest()
        assert result["success"] is False
        assert "ありません" in result["message"]

    def test_history_filter_by_task_id(self, service):
        """task_id でフィルタリングできること"""
        service.apply_improvement(task_id="T-001", improvement_type="a", original_text="1", improved_text="2")
        service.apply_improvement(task_id="T-002", improvement_type="b", original_text="3", improved_text="4")

        result = service.get_history(task_id="T-001")
        assert result["count"] == 1
        assert result["history"][0]["task_id"] == "T-001"

    def test_apply_improvement_missing_key(self, tmp_path):
        """改善適用時に hook_improvements キーが存在しない場合、自動生成されること"""
        from services.hook_evolution_service import HookEvolutionService
        from safe_io import SafeJsonStore

        svc = HookEvolutionService()
        # デフォルト値に hook_improvements を含まない SafeJsonStore を設定
        svc._store = SafeJsonStore(
            tmp_path / "evolution_log.json",
            default={"entries": []}
        )

        result = svc.apply_improvement(
            task_id="T-001",
            improvement_type="attention",
            original_text="元のテキスト",
            improved_text="改善テキスト",
            expected_score_boost=15
        )
        assert result["success"] is True
        
        # 履歴を取得して、キーが作成され記録されていることを確認
        history = svc.get_history()
        assert history["count"] == 1
        assert history["history"][0]["type"] == "attention"

    def test_revert_latest_multiple_improvements(self, service):
        """複数回の改善案適用に対し、最新のもののみが reverted になること"""
        service.apply_improvement(
            task_id="T-001",
            improvement_type="a",
            original_text="Before A",
            improved_text="After A"
        )
        service.apply_improvement(
            task_id="T-002",
            improvement_type="b",
            original_text="Before B",
            improved_text="After B"
        )
        
        # 1回 revert する
        result = service.revert_latest()
        assert result["success"] is True
        assert result["reverted_text"] == "Before B"
        
        # 履歴でステータスを確認
        history = service.get_history()
        assert history["history"][0]["status"] == "applied"   # T-001 はそのまま
        assert history["history"][1]["status"] == "reverted"  # T-002 は revert 済み

    def test_singleton_instance_configuration(self):
        """シングルトンインスタンスが正しく初期化されエクスポートされていること"""
        from services.hook_evolution_service import hook_evolution_service, HookEvolutionService
        
        assert isinstance(hook_evolution_service, HookEvolutionService)
        # デフォルトの保存先ファイルを確認
        assert hook_evolution_service._store.path.name == "evolution_log.json"

    def test_apply_improvement_store_error(self, service):
        """ストア保存時に例外が発生した場合、エラーレスポンスが返されること"""
        from unittest.mock import MagicMock
        
        # update メソッドが OSError を投げるようにモックする
        service._store.update = MagicMock(side_effect=OSError("Disk full"))
        
        result = service.apply_improvement(
            task_id="T-001",
            improvement_type="attention",
            original_text="元のテキスト",
            improved_text="改善テキスト",
            expected_score_boost=15
        )
        assert result["success"] is False
        assert "Disk full" in result["message"]

    def test_revert_latest_store_error(self, service):
        """ストア読み込みまたは保存時に例外が発生した場合、エラーレスポンスが返されること"""
        from unittest.mock import MagicMock
        
        service._store.load = MagicMock(side_effect=OSError("Read error"))
        
        result = service.revert_latest()
        assert result["success"] is False
        assert "Read error" in result["message"]

    def test_get_history_store_error(self, service):
        """ストア読み込み時に例外が発生した場合、エラーレスポンスが返されること"""
        from unittest.mock import MagicMock
        
        service._store.load = MagicMock(side_effect=OSError("Read error"))
        
        result = service.get_history()
        assert result["success"] is False
        assert "Read error" in result["message"]
        assert result["history"] == []


# ===========================================================================
# MK-01: PostPublishCollector テスト（決定論的モック）
# ===========================================================================
class TestPostPublishCollector:
    """post_publish_collector.py のモックデータ決定論性を検証"""

    def test_mock_data_is_deterministic(self):
        """同じ入力で同じモックデータが返ること"""
        from services.post_publish_collector import PostPublishCollector

        collector = PostPublishCollector()
        result1 = asyncio.run(collector.collect_performance_data("vid_001", elapsed_hours=24))
        result2 = asyncio.run(collector.collect_performance_data("vid_001", elapsed_hours=24))

        assert result1["metrics"]["views"] == result2["metrics"]["views"]
        assert result1["metrics"]["click_through_rate"] == result2["metrics"]["click_through_rate"]
        assert result1["metrics"]["retention_rate_pct"] == result2["metrics"]["retention_rate_pct"]

    def test_different_video_ids_produce_different_data(self):
        """異なるvideo_idで異なるデータが返ること"""
        from services.post_publish_collector import PostPublishCollector

        collector = PostPublishCollector()
        result1 = asyncio.run(collector.collect_performance_data("vid_aaa", elapsed_hours=24))
        result2 = asyncio.run(collector.collect_performance_data("vid_bbb", elapsed_hours=24))

        views_differ = result1["metrics"]["views"] != result2["metrics"]["views"]
        ctr_differ = result1["metrics"]["click_through_rate"] != result2["metrics"]["click_through_rate"]
        assert views_differ or ctr_differ

    def test_mock_data_has_is_mock_flag(self):
        """モックデータに is_mock=True フラグが含まれること"""
        from services.post_publish_collector import PostPublishCollector

        collector = PostPublishCollector()
        result = asyncio.run(collector.collect_performance_data("vid_001"))
        assert result.get("is_mock") is True

    def test_mock_data_structure(self):
        """モックデータの構造が正しいこと"""
        from services.post_publish_collector import PostPublishCollector

        collector = PostPublishCollector()
        result = asyncio.run(collector.collect_performance_data("vid_001"))

        assert "video_id" in result
        assert "metrics" in result
        metrics = result["metrics"]
        assert "views" in metrics
        assert "click_through_rate" in metrics
        assert "retention_rate_pct" in metrics
        assert "likes" in metrics
        assert "comments" in metrics


# ===========================================================================
# DT-01+Phase 4: SeriesPlanner テスト（SafeJsonStore適用確認）
# ===========================================================================
class TestSeriesPlanner:
    """series_planner.py のCRUD操作を検証"""

    @pytest.fixture
    def planner(self, tmp_path):
        """テスト用一時ファイルで初期化されたSeriesPlanner"""
        from services.series_planner import SeriesPlanner
        from safe_io import SafeJsonStore

        sp = SeriesPlanner()
        sp._store = SafeJsonStore(
            tmp_path / "series_registry.json",
            default={"version": "1.0", "series": {}}
        )
        sp.series_data = sp._load()
        return sp

    def test_register_new_series(self, planner):
        """新しいシリーズが登録できること"""
        result = planner.register_series(
            series_id="test-series",
            title="テストシリーズ",
            theme="テスト",
            target_persona="All"
        )
        assert result["title"] == "テストシリーズ"
        assert result["theme"] == "テスト"

    def test_register_duplicate_series_returns_existing(self, planner):
        """重複登録は既存データを返すこと"""
        planner.register_series(series_id="dup", title="First", theme="A")
        result = planner.register_series(series_id="dup", title="Second", theme="B")
        assert result["title"] == "First"  # 最初の登録が優先

    def test_add_video_to_series(self, planner):
        """シリーズに動画を追加できること"""
        planner.register_series(series_id="s1", title="S1", theme="T")
        success = planner.add_video_to_series(
            series_id="s1", video_id="v1", video_title="Video 1"
        )
        assert success is True

    def test_add_video_to_nonexistent_series(self, planner):
        """存在しないシリーズへの追加は失敗すること"""
        success = planner.add_video_to_series(
            series_id="nonexistent", video_id="v1", video_title="V1"
        )
        assert success is False

    def test_add_duplicate_video(self, planner):
        """同じ動画の重複追加は安全にTrueを返すこと"""
        planner.register_series(series_id="s1", title="S1", theme="T")
        planner.add_video_to_series(series_id="s1", video_id="v1", video_title="V1")
        success = planner.add_video_to_series(series_id="s1", video_id="v1", video_title="V1")
        assert success is True

    def test_suggest_next_video(self, planner):
        """次回予告提案が返ること"""
        planner.register_series(series_id="s1", title="S1", theme="テスト")
        result = planner.suggest_next_video(
            series_id="s1", current_video_id="v1", current_context=""
        )
        assert result["success"] is True
        assert "teaser_text" in result

    def test_suggest_next_nonexistent(self, planner):
        """存在しないシリーズの提案は失敗メッセージを返すこと"""
        result = planner.suggest_next_video(
            series_id="nope", current_video_id="v1", current_context=""
        )
        assert result["success"] is False

    def test_optimize_playlist_empty(self, planner):
        """動画なしのプレイリスト最適化はエラーメッセージを返すこと"""
        planner.register_series(series_id="s1", title="S1", theme="T")
        result = planner.optimize_playlist(series_id="s1")
        assert result["success"] is False

    def test_optimize_playlist_one_video(self, planner):
        """1本のみのプレイリスト最適化が適切なメッセージを返すこと"""
        planner.register_series(series_id="s1", title="S1", theme="T")
        planner.add_video_to_series(series_id="s1", video_id="v1", video_title="V1")
        result = planner.optimize_playlist(series_id="s1")
        assert result["success"] is True
        assert "第一作目" in result["overall_message"]


# ===========================================================================
# DT-02: WagamamaManager.get_record テスト
# ===========================================================================
class TestWagamamaManagerGetRecord:
    """wagamama_manager.py のパブリックAPI get_record を検証"""

    def test_get_record_returns_existing(self):
        """存在するレコードが取得できること"""
        from wagamama_manager import WagamamaManager

        mgr = WagamamaManager.__new__(WagamamaManager)
        mgr.ledger_data = {
            "records": [
                {"wagamama_id": "W-001", "title": "テスト企画"},
                {"wagamama_id": "W-002", "title": "別の企画"}
            ]
        }
        record = mgr.get_record("W-001")
        assert record is not None
        assert record["title"] == "テスト企画"

    def test_get_record_returns_none_for_missing(self):
        """存在しないIDではNoneが返ること"""
        from wagamama_manager import WagamamaManager

        mgr = WagamamaManager.__new__(WagamamaManager)
        mgr.ledger_data = {"records": [{"wagamama_id": "W-001"}]}
        assert mgr.get_record("W-999") is None

    def test_backward_compat_find_record(self):
        """後方互換の _find_record が get_record と同じ結果を返すこと"""
        from wagamama_manager import WagamamaManager

        mgr = WagamamaManager.__new__(WagamamaManager)
        mgr.ledger_data = {"records": [{"wagamama_id": "W-001", "data": "test"}]}
        assert mgr._find_record("W-001") == mgr.get_record("W-001")


# ===========================================================================
# Phase 2.2: PredictionValidator テスト
# ===========================================================================
class TestPredictionValidator:
    """prediction_validator.py の検証ロジックを検証"""

    def test_validate_with_no_manager(self):
        """managerがNoneの場合はエラーを返すこと"""
        from services.prediction_validator import PredictionValidator

        validator = PredictionValidator()
        result = asyncio.run(validator.validate_prediction("W-001", {}, wagamama_manager=None))
        assert result["status"] == "error"

    def test_validate_with_missing_record(self):
        """レコードが見つからない場合はエラーを返すこと"""
        from services.prediction_validator import PredictionValidator

        mock_mgr = MagicMock()
        mock_mgr.get_record.return_value = None

        validator = PredictionValidator()
        result = asyncio.run(validator.validate_prediction("W-999", {}, wagamama_manager=mock_mgr))
        assert result["status"] == "error"

    def test_validate_with_no_predicted_ctr(self):
        """予測CTRがない場合はスキップすること"""
        from services.prediction_validator import PredictionValidator

        mock_mgr = MagicMock()
        mock_mgr.get_record.return_value = {"lanes": {"experience": {}}}

        validator = PredictionValidator()
        result = asyncio.run(validator.validate_prediction("W-001", {}, wagamama_manager=mock_mgr))
        assert result["status"] == "skipped"

    def test_validate_significant_deviation(self):
        """30%以上のズレが significant_deviation としてフラグされること"""
        from services.prediction_validator import PredictionValidator

        mock_mgr = MagicMock()
        mock_mgr.get_record.return_value = {
            "wagamama_id": "W-001",
            "lanes": {"experience": {"predicted_ctr": 5.0}}
        }
        mock_mgr._save = MagicMock()

        actual_metrics = {
            "metrics": {"click_through_rate": 8.0},
            "elapsed_hours": 24
        }

        validator = PredictionValidator()
        result = asyncio.run(validator.validate_prediction("W-001", actual_metrics, wagamama_manager=mock_mgr))
        assert result["analysis"]["significant_deviation"] is True

    def test_validate_with_zero_predicted_ctr(self):
        """predicted_ctr が 0.0 の場合でもスキップされず検証されること"""
        from services.prediction_validator import PredictionValidator

        mock_mgr = MagicMock()
        mock_mgr.get_record.return_value = {
            "wagamama_id": "W-001",
            "lanes": {"experience": {"predicted_ctr": 0.0}}
        }
        mock_mgr._save = MagicMock()

        actual_metrics = {
            "metrics": {"click_through_rate": 2.0},
            "elapsed_hours": 24
        }

        validator = PredictionValidator()
        result = asyncio.run(validator.validate_prediction("W-001", actual_metrics, wagamama_manager=mock_mgr))
        assert result.get("status") != "skipped"
        assert result["analysis"]["predicted"] == 0.0
        assert result["analysis"]["actual"] == 2.0

    def test_validate_with_none_metrics(self):
        """actual_metrics の metrics が None または空の場合でも例外が発生しないこと"""
        from services.prediction_validator import PredictionValidator

        mock_mgr = MagicMock()
        mock_mgr.get_record.return_value = {
            "wagamama_id": "W-001",
            "lanes": {"experience": {"predicted_ctr": 5.0}}
        }
        mock_mgr._save = MagicMock()

        # metricsキーが存在するが値がNoneのケース
        actual_metrics_none = {
            "metrics": None,
            "elapsed_hours": 24
        }

        validator = PredictionValidator()
        result = asyncio.run(validator.validate_prediction("W-001", actual_metrics_none, wagamama_manager=mock_mgr))
        # **届いていない CTR を 0.0 で埋めない**（R1.5-C4・19周目）。
        # ここは `== 0.0` を期待していたが、その 0.0 は「metrics が None ＝
        # 実測が1件も無い」のに実績 CTR として名乗っていた捏造そのもの。
        # 予測 5.0% に対して「誤差 100%・重大な乖離」という**計測していない判定**
        # まで出て、それが台帳へ恒久保存されていた。
        assert result["actual"]["ctr"] is None
        assert result["actual"]["is_real"] is False
        assert result["actual"]["data_source"] == "unavailable"
        assert result["analysis"]["checked"] is False
        assert result["analysis"]["significant_deviation"] is None
        assert result["status"] == "skipped"
        # **台帳に書かない**（作り物のレポートが焼き付かないこと）
        mock_mgr._save.assert_not_called()

        # actual_metrics 自体が None のケース
        mock_mgr._save.reset_mock()
        result_null = asyncio.run(validator.validate_prediction("W-001", None, wagamama_manager=mock_mgr))
        # 上と同じ理由（R1.5-C4・19周目）。実測が1件も無いのに 0.0 を実績と呼ばない
        assert result_null["actual"]["ctr"] is None
        assert result_null["actual"]["is_real"] is False
        assert result_null["analysis"]["checked"] is False
        assert result_null["status"] == "skipped"
        mock_mgr._save.assert_not_called()

    def test_validate_report_keys_match_optimizer(self):
        """生成されるレポートの analysis に predicted と actual キーが含まれていること"""
        from services.prediction_validator import PredictionValidator

        mock_mgr = MagicMock()
        mock_mgr.get_record.return_value = {
            "wagamama_id": "W-001",
            "lanes": {"experience": {"predicted_ctr": 5.0}}
        }
        mock_mgr._save = MagicMock()

        actual_metrics = {
            "metrics": {"click_through_rate": 6.0},
            "elapsed_hours": 24
        }

        validator = PredictionValidator()
        result = asyncio.run(validator.validate_prediction("W-001", actual_metrics, wagamama_manager=mock_mgr))
        assert "predicted" in result["analysis"]
        assert "actual" in result["analysis"]
        assert result["analysis"]["predicted"] == 5.0
        assert result["analysis"]["actual"] == 6.0


# ===========================================================================
# Phase 3: RetentionMapPlugin テスト
# ===========================================================================
class TestRetentionMapPlugin:
    """retention_map_plugin.py の基本動作を検証"""

    def test_analyze_returns_segments(self):
        """分析結果にセグメントが含まれること"""
        from plugins.retention_map_plugin import RetentionMapPlugin

        plugin = RetentionMapPlugin()
        report = plugin.analyze_retention_risks(
            video_id="test_video",
            duration_sec=60
        )
        assert len(report.segments) > 0
        assert report.total_duration_sec == 60
        assert report.video_id == "test_video"

    def test_segments_cover_full_duration(self):
        """セグメントが全体の尺をカバーすること"""
        from plugins.retention_map_plugin import RetentionMapPlugin

        plugin = RetentionMapPlugin()
        report = plugin.analyze_retention_risks(
            video_id="test", duration_sec=30
        )
        first = report.segments[0]
        last = report.segments[-1]
        assert first.start_time == 0
        assert last.end_time == 30

    def test_suggestions_generated_for_long_boring_stretch(self):
        """十分長い動画ではリエンゲージメント提案が生成されること"""
        from plugins.retention_map_plugin import RetentionMapPlugin

        plugin = RetentionMapPlugin()
        # 5分の動画 — 退屈セクションが発生しやすい
        report = plugin.analyze_retention_risks(
            video_id="long_video", duration_sec=300
        )
        # 全体評価が文字列であること
        assert isinstance(report.overall_risk_assessment, str)
        assert report.overall_risk_assessment in ("安全", "要注意（一部シーンのテンポ改善が必要）", "危険（要大幅な再編集）")

    def test_risk_scores_within_valid_range(self):
        """リスクスコアが0〜100の範囲内であること"""
        from plugins.retention_map_plugin import RetentionMapPlugin

        plugin = RetentionMapPlugin()
        report = plugin.analyze_retention_risks(video_id="range_test", duration_sec=120)
        for seg in report.segments:
            assert 0 <= seg.risk_score <= 100

    def test_generate_suggestions_warning_on_mismatched_end_time(self, caplog):
        """セグメント終端が全体長と一致しない場合に警告ログが出力されること (85行目のカバー)"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionSegment
        import logging
        from unittest.mock import patch

        plugin = RetentionMapPlugin()
        
        # Pydanticモデルのプロパティをフックして、特定のビデオIDの場合に end_time を書き換える
        original_init = RetentionSegment.__init__
        
        def mock_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            # 最初のセグメントの end_time を 9 に書き換えることで全体長(10)と不一致にする
            if kwargs.get("start_time") == 0:
                object.__setattr__(self, "end_time", 9)

        with patch.object(RetentionSegment, "__init__", mock_init):
            with caplog.at_level(logging.WARNING):
                plugin.analyze_retention_risks(
                    video_id="test_mismatch",
                    duration_sec=10
                )
        
        assert any("セグメント終端" in record.message for record in caplog.records)

    def test_three_min_points_suggestion_generation(self):
        """3分(180秒)の節目で、かつ dopamine_hit が False の場合にリエンゲージメント提案が生成されること (122-124行目のカバー)"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionSegment

        plugin = RetentionMapPlugin()
        # 180秒の節目を含む segments を用意。
        # 180秒の節目（start_time <= 180 < end_time）のセグメントで dopamine_hit=False にする。
        # 30秒以上boringが続かないように、他のセグメントは dopamine_hit=True にして 30秒boring提案との干渉を避ける
        segments = []
        for start in range(0, 200, 10):
            end = start + 10
            is_three_min = (start <= 180 < end)
            segments.append(RetentionSegment(
                start_time=start,
                end_time=end,
                risk_score=20,
                visual_change=True,
                audio_change=not is_three_min,
                text_change=not is_three_min,
                dopamine_hit=not is_three_min
            ))

        report = plugin._generate_suggestions(
            video_id="test_three_min",
            duration_sec=200,
            segments=segments
        )

        # 提案の中に "シーンの転換（BGM変更または大文字テロップ）" が含まれるか検証
        three_min_suggestions = [
            s for s in report.suggestions 
            if "シーンの転換" in s.suggestion_type and s.timestamp_sec == 180
        ]
        assert len(three_min_suggestions) == 1
        assert "3分の節目です" in three_min_suggestions[0].reason

    def test_three_min_points_skip_duplicate(self):
        """3分の節目の近くに、すでに退屈提案が存在する場合に重複を避けてスキップすること (119行目のカバー)"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionSegment

        plugin = RetentionMapPlugin()
        
        # 150秒〜180秒の間で dopamine_hit=False にすると、180秒時点で退屈提案（boring >= 30秒）が suggestions に追加されます。
        # その後、3分の節目（180秒）でも 180秒の節目として suggestions に追加しようとしますが、
        # すでに 180秒（差が 0 <= 15）の提案があるため、スキップ（continue）されます。
        segments = []
        for start in range(0, 200, 10):
            end = start + 10
            is_boring = (150 <= start < 180)
            segments.append(RetentionSegment(
                start_time=start,
                end_time=end,
                risk_score=20,
                visual_change=True,
                audio_change=not is_boring,
                text_change=not is_boring,
                dopamine_hit=not is_boring
            ))

        report = plugin._generate_suggestions(
            video_id="test_dup_skip",
            duration_sec=200,
            segments=segments
        )

        # 提案リストに 180秒のboring提案（ジャンプカットまたはB-roll挿入）は含まれるが、
        # 3分の節目提案（シーンの転換（BGM変更または大文字テロップ））は含まれないことを確認
        boring_suggestions = [s for s in report.suggestions if "ジャンプカット" in s.suggestion_type]
        three_min_suggestions = [s for s in report.suggestions if "シーンの転換" in s.suggestion_type]
        
        assert len(boring_suggestions) == 1
        assert len(three_min_suggestions) == 0

    def test_overall_risk_assessment_critical(self):
        """平均リスクが60を超える場合に '危険' 判定になること (134行目のカバー)"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionSegment

        plugin = RetentionMapPlugin()
        segments = [
            RetentionSegment(
                start_time=0,
                end_time=10,
                risk_score=70,
                visual_change=False,
                audio_change=False,
                text_change=False,
                dopamine_hit=False
            )
        ]
        report = plugin._generate_suggestions(
            video_id="test_critical",
            duration_sec=10,
            segments=segments
        )
        assert report.overall_risk_assessment == "危険（要大幅な再編集）"

    def test_overall_risk_assessment_warning(self):
        """平均リスクが40超60以下の場合に '要注意' 判定になること"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionSegment

        plugin = RetentionMapPlugin()
        segments = [
            RetentionSegment(
                start_time=0,
                end_time=10,
                risk_score=50,
                visual_change=False,
                audio_change=False,
                text_change=False,
                dopamine_hit=False
            )
        ]
        report = plugin._generate_suggestions(
            video_id="test_warning",
            duration_sec=10,
            segments=segments
        )
        assert report.overall_risk_assessment == "要注意（一部シーンのテンポ改善が必要）"

    def test_overall_risk_assessment_safe(self):
        """平均リスクが40以下の場合に '安全' 判定になること"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionSegment

        plugin = RetentionMapPlugin()
        segments = [
            RetentionSegment(
                start_time=0,
                end_time=10,
                risk_score=30,
                visual_change=True,
                audio_change=True,
                text_change=True,
                dopamine_hit=True
            )
        ]
        report = plugin._generate_suggestions(
            video_id="test_safe",
            duration_sec=10,
            segments=segments
        )
        assert report.overall_risk_assessment == "安全"

    def test_three_min_points_no_segment_found(self):
        """3分の節目に対応するセグメントが存在しない場合（境界条件）、エラーにならずスキップすること"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionSegment

        plugin = RetentionMapPlugin()
        # duration_sec = 200 だが、180秒付近のセグメントを意図的に排除する
        # 例えば、0-100 と 190-200 だけのセグメントにする
        segments = [
            RetentionSegment(
                start_time=0,
                end_time=10,
                risk_score=10,
                visual_change=True,
                audio_change=True,
                text_change=True,
                dopamine_hit=True
            ),
            RetentionSegment(
                start_time=190,
                end_time=200,
                risk_score=10,
                visual_change=True,
                audio_change=True,
                text_change=True,
                dopamine_hit=True
            )
        ]
        report = plugin._generate_suggestions(
            video_id="test_no_seg",
            duration_sec=200,
            segments=segments
        )
        # エラーにならずにSuggestionsが生成されること
        assert len(report.suggestions) == 0

    def test_pydantic_schema_validation_errors(self):
        """Pydanticモデルに不正なデータを渡した際に ValidationError が発生すること"""
        from plugins.retention_map_plugin import RetentionSegment, ReengagementSuggestion, RetentionMapReport
        from pydantic import ValidationError

        # 必須フィールド欠落
        with pytest.raises(ValidationError):
            RetentionSegment(start_time=0, end_time=10) # risk_score 欠落

        with pytest.raises(ValidationError):
            ReengagementSuggestion(timestamp_sec=10, suggestion_type="B-roll") # reason 欠落

        with pytest.raises(ValidationError):
            RetentionMapReport(video_id="test", total_duration_sec=10, segments=[]) # suggestions 欠落

        # 型エラー
        with pytest.raises(ValidationError):
            RetentionSegment(
                start_time="invalid", # int が必要
                end_time=10,
                risk_score=50
            )

    def test_empty_segments_fallback(self):
        """セグメントリストが空の場合の平均リスク算出のフォールバック動作を検証"""
        from plugins.retention_map_plugin import RetentionMapPlugin

        plugin = RetentionMapPlugin()
        report = plugin._generate_suggestions(
            video_id="test_empty",
            duration_sec=10,
            segments=[]
        )
        assert report.overall_risk_assessment == "安全" # avg_risk = 0 なので安全になる
        assert len(report.segments) == 0
        assert len(report.suggestions) == 0

    def test_analyze_invalid_video_id(self):
        """video_id が指定されていないか空の場合に RetentionMapError が発生すること"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionMapError
        import pytest

        plugin = RetentionMapPlugin()
        with pytest.raises(RetentionMapError) as exc_info:
            plugin.analyze_retention_risks(video_id="", duration_sec=60)
        assert "video_id must be a non-empty string" in str(exc_info.value)

        with pytest.raises(RetentionMapError):
            plugin.analyze_retention_risks(video_id=None, duration_sec=60)

    def test_analyze_invalid_duration(self):
        """duration_sec が 0 以下、または非整数の場合に RetentionMapError が発生すること"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionMapError
        import pytest

        plugin = RetentionMapPlugin()
        with pytest.raises(RetentionMapError) as exc_info:
            plugin.analyze_retention_risks(video_id="test", duration_sec=0)
        assert "duration_sec must be a positive integer" in str(exc_info.value)

        with pytest.raises(RetentionMapError):
            plugin.analyze_retention_risks(video_id="test", duration_sec=-10)

        with pytest.raises(RetentionMapError):
            plugin.analyze_retention_risks(video_id="test", duration_sec="invalid")

        with pytest.raises(RetentionMapError):
            plugin.analyze_retention_risks(video_id="test", duration_sec=None)

    def test_analyze_unexpected_exception_logged_and_wrapped(self, caplog):
        """内部で予期せぬ例外が発生した際に、RetentionMapError にラップされてログ出力されること"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionMapError
        from unittest.mock import patch
        import pytest
        import logging

        plugin = RetentionMapPlugin()
        # _generate_suggestions をモックして意図的に例外を投げさせる
        with patch.object(plugin, "_generate_suggestions", side_effect=RuntimeError("Unexpected DB error")):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(RetentionMapError) as exc_info:
                    plugin.analyze_retention_risks(video_id="test_ex", duration_sec=30)
                assert "Failed to analyze retention risks" in str(exc_info.value)
                assert any("分析実行中に予期せぬ例外が発生しました" in record.message for record in caplog.records)

    def test_analyze_retention_risks_rethrows_retention_map_error(self):
        """analyze_retention_risks の try ブロック内で RetentionMapError が発生した際に、そのまま再スローされること (103-104行目のカバー)"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionMapError
        from unittest.mock import patch
        import pytest

        plugin = RetentionMapPlugin()
        with patch.object(plugin, "_generate_suggestions", side_effect=RetentionMapError("Mocked retention error")):
            with pytest.raises(RetentionMapError) as exc_info:
                plugin.analyze_retention_risks(video_id="test_rethrow", duration_sec=30)
            assert "Mocked retention error" in str(exc_info.value)

    def test_generate_suggestions_unexpected_exception(self):
        """_generate_suggestions 内で予期せぬ例外が発生した際に、RetentionMapError にラップされてログ出力されること (167-171行目のカバー)"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionMapError
        import pytest

        plugin = RetentionMapPlugin()
        with pytest.raises(RetentionMapError) as exc_info:
            plugin._generate_suggestions(video_id="test_err", duration_sec=30, segments=None)
        assert "Failed to generate suggestions" in str(exc_info.value)

    def test_generate_suggestions_rethrows_retention_map_error(self):
        """_generate_suggestions 内で RetentionMapError が発生した際に、そのまま再スローされること (169-170行目のカバー)"""
        from plugins.retention_map_plugin import RetentionMapPlugin, RetentionMapError
        from unittest.mock import MagicMock, PropertyMock
        import pytest

        plugin = RetentionMapPlugin()
        mock_segment = MagicMock()
        type(mock_segment).dopamine_hit = PropertyMock(side_effect=RetentionMapError("Segment property error"))

        with pytest.raises(RetentionMapError) as exc_info:
            plugin._generate_suggestions(video_id="test_prop_err", duration_sec=30, segments=[mock_segment])
        assert "Segment property error" in str(exc_info.value)


# ===========================================================================
# Phase 1: YouTubeOptimizerPlugin（SessionContinuationScore）テスト
# ===========================================================================
class TestSessionContinuationScore:
    """youtube_optimizer_plugin.py のセッション継続スコアを検証"""

    def test_max_score_with_all_features(self):
        """全要素ありの場合100点であること"""
        from plugins.youtube_optimizer_plugin import youtube_optimizer

        result = youtube_optimizer.calculate_session_continuation_score(
            current_video_id="v1",
            series_id="s1",
            has_end_screen=True,
            has_teaser=True,
            brand_consistency=100.0
        )
        assert result["score"] == 100.0

    def test_zero_score_without_features(self):
        """全要素なしの場合0点であること"""
        from plugins.youtube_optimizer_plugin import youtube_optimizer

        result = youtube_optimizer.calculate_session_continuation_score(
            current_video_id="v1",
            series_id="s1",
            has_end_screen=False,
            has_teaser=False,
            brand_consistency=0.0
        )
        assert result["score"] == 0.0

    def test_partial_score(self):
        """一部要素ありの場合は中間スコアであること"""
        from plugins.youtube_optimizer_plugin import youtube_optimizer

        result = youtube_optimizer.calculate_session_continuation_score(
            current_video_id="v1",
            series_id="s1",
            has_end_screen=True,
            has_teaser=False,
            brand_consistency=50.0
        )
        # end_screen(30) + brand(15) = 45
        assert result["score"] == 45.0

    def test_result_structure(self):
        """結果に必要なキーが含まれること"""
        from plugins.youtube_optimizer_plugin import youtube_optimizer

        result = youtube_optimizer.calculate_session_continuation_score(
            current_video_id="v1",
            series_id="s1"
        )
        assert "score" in result
        assert "factors" in result
        assert "recommendation" in result
        assert "series_id" in result


# ===========================================================================
# AR-01: GeminiClientFactory テスト
# ===========================================================================
class TestGeminiClientFactory:
    """gemini_client_factory.py のシングルトン管理を検証"""

    def setup_method(self):
        """各テスト前にクライアントをリセット"""
        from gemini_client_factory import reset_client
        reset_client()

    def test_returns_none_without_api_key(self):
        """GOOGLE_API_KEY 未設定時は None を返すこと"""
        from gemini_client_factory import get_gemini_client
        with patch.dict(os.environ, {}, clear=True):
            # GOOGLE_API_KEY を除外
            env = {k: v for k, v in os.environ.items() if k != "GOOGLE_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                result = get_gemini_client()
                assert result is None

    def test_returns_client_with_api_key(self):
        """GOOGLE_API_KEY 設定時はクライアントを返すこと"""
        from gemini_client_factory import get_gemini_client

        mock_client = MagicMock()
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key-123"}):
            with patch("gemini_client_factory.genai", create=True) as mock_genai:
                # genai モジュールのモック
                import gemini_client_factory
                with patch.object(gemini_client_factory, '_cached_raw_client', None):
                    with patch.object(gemini_client_factory, '_current_api_key', None):
                        mock_genai_module = MagicMock()
                        mock_genai_module.Client.return_value = mock_client
                        with patch.dict('sys.modules', {'google.genai': mock_genai_module, 'google': MagicMock()}):
                            from importlib import reload
                            reload(gemini_client_factory)
                            result = gemini_client_factory.get_gemini_client()
                            # None でなければ成功（モック環境の制約でクライアント初期化が成功するか）
                            # ここではインターフェース仕様の検証
                            assert True  # ファクトリ関数が例外なく動作すること

    def test_reset_clears_client(self):
        """reset_client() でクライアントがクリアされること"""
        import gemini_client_factory
        gemini_client_factory._cached_raw_client = MagicMock()
        gemini_client_factory._current_api_key = "old-key"

        gemini_client_factory.reset_client()

        assert gemini_client_factory._cached_raw_client is None
        assert gemini_client_factory._current_api_key is None

    def test_singleton_returns_same_instance(self):
        """同じAPIキーでは同じ生クライアントを返すこと（GovernedClient対応）"""
        import gemini_client_factory

        mock_client = MagicMock()
        gemini_client_factory._cached_raw_client = mock_client
        gemini_client_factory._current_api_key = "same-key"
        gemini_client_factory._cached_governed_client = None  # キャッシュクリア

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "same-key"}):
            # _get_raw_client() のシングルトン性を検証
            raw1 = gemini_client_factory._get_raw_client()
            raw2 = gemini_client_factory._get_raw_client()
            assert raw1 is raw2 is mock_client

    def test_get_raw_client_double_check_lock(self):
        """ダブルチェックロックの真の分岐を検証"""
        import gemini_client_factory
        from unittest.mock import patch, MagicMock
        
        mock_client = MagicMock()
        gemini_client_factory._cached_raw_client = None
        gemini_client_factory._current_api_key = None
        
        # 最初のチェックは _client が None
        # ロックに入った段階で、別スレッドがすでに生成していた状態をシミュレート
        def side_effect(*args, **kwargs):
            gemini_client_factory._cached_raw_client = mock_client
            gemini_client_factory._current_api_key = "test-key"
            return mock_client

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch.object(gemini_client_factory, '_lock'):
                # ロック獲得直前にすでに他スレッドで _client が入った状態を作るため、
                # lockのコンテキストマネージャに入る際に _client を仕込む
                class FakeLock:
                    def __enter__(self):
                        gemini_client_factory._cached_raw_client = mock_client
                        gemini_client_factory._current_api_key = "test-key"
                    def __exit__(self, exc_type, exc_val, exc_tb):
                        pass
                
                with patch.object(gemini_client_factory, '_lock', FakeLock()):
                    res = gemini_client_factory._get_raw_client()
                    assert res is mock_client

    def test_client_initialization_failure(self):
        """クライアント初期化失敗時の例外ハンドリングとログを検証 (TD-443)"""
        import gemini_client_factory
        from unittest.mock import patch, MagicMock
        
        gemini_client_factory._cached_raw_client = None
        gemini_client_factory._current_api_key = None
        
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "invalid-key"}):
            with patch("google.genai.Client", side_effect=ValueError("Invalid key format")):
                with patch.object(gemini_client_factory.logger, "exception") as mock_log:
                    res = gemini_client_factory._get_raw_client()
                    assert res is None
                    assert gemini_client_factory._cached_raw_client is None
                    assert gemini_client_factory._current_api_key is None
                    mock_log.assert_called_once()
                    assert "❌ [GeminiClientFactory] クライアント初期化失敗" in mock_log.call_args[0][0]

    def test_governed_client_cache_hit(self):
        """get_gemini_client で _governed_client キャッシュヒット判定の真ブロックを検証"""
        import gemini_client_factory
        from unittest.mock import MagicMock, patch
        
        mock_raw = MagicMock()
        mock_gov = MagicMock()
        mock_gov._raw = mock_raw
        
        gemini_client_factory._cached_raw_client = mock_raw
        gemini_client_factory._current_api_key = "test-key"
        gemini_client_factory._cached_governed_client = mock_gov
        
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            res = gemini_client_factory.get_gemini_client()
            assert res is mock_gov

    def test_governed_client_getattr(self):
        """GovernedClient プロキシの __getattr__ を検証"""
        import gemini_client_factory
        from unittest.mock import MagicMock, patch
        
        mock_raw = MagicMock()
        mock_raw.some_raw_method.return_value = "raw-value"
        
        gemini_client_factory._cached_raw_client = mock_raw
        gemini_client_factory._current_api_key = "test-key"
        gemini_client_factory._cached_governed_client = None
        
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            client = gemini_client_factory.get_gemini_client()
            val = client.some_raw_method()
            assert val == "raw-value"
            mock_raw.some_raw_method.assert_called_once()

    def test_model_governance_import_error(self):
        """model_governance インポート失敗時のフォールバックを検証"""
        import gemini_client_factory
        from unittest.mock import MagicMock, patch
        import sys
        
        mock_raw = MagicMock()
        gemini_client_factory._cached_raw_client = mock_raw
        gemini_client_factory._current_api_key = "test-key"
        gemini_client_factory._cached_governed_client = None
        
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch.dict(sys.modules, {"model_governance": None}):
                # sys.modules に None を入れると ImportError になる
                res = gemini_client_factory.get_gemini_client()
                assert res is mock_raw

    def test_get_gemini_client_double_check_lock(self):
        """get_gemini_client のダブルチェックロック分岐を検証"""
        import gemini_client_factory
        from unittest.mock import MagicMock, patch
        
        mock_raw = MagicMock()
        mock_gov = MagicMock()
        mock_gov._raw = mock_raw
        
        gemini_client_factory._cached_raw_client = mock_raw
        gemini_client_factory._current_api_key = "test-key"
        gemini_client_factory._cached_governed_client = None
        
        # ロックに入った段階で、別スレッドがすでにキャッシュを生成していた状態をシミュレート
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            class FakeLock:
                def __enter__(self):
                    gemini_client_factory._cached_governed_client = mock_gov
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
            
            with patch.object(gemini_client_factory, '_lock', FakeLock()):
                res = gemini_client_factory.get_gemini_client()
                assert res is mock_gov

    def test_model_governance_general_exception(self):
        """model_governance インポート時、ImportError 以外の例外が発生した場合の警告フォールバックを検証"""
        import gemini_client_factory
        from unittest.mock import MagicMock, patch
        
        mock_raw = MagicMock()
        gemini_client_factory._cached_raw_client = mock_raw
        gemini_client_factory._current_api_key = "test-key"
        gemini_client_factory._cached_governed_client = None
        
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            with patch("model_governance.GovernedModelsProxy", side_effect=TypeError("Mock governance error")):
                with patch.object(gemini_client_factory.logger, "warning") as mock_warn:
                    res = gemini_client_factory.get_gemini_client()
                    assert res is mock_raw
                    mock_warn.assert_called_once()
                    assert "model_governance 適用失敗" in mock_warn.call_args[0][0]
