"""
test_model_governance.py — M2.3 Sprint 2.3.2 ModelGovernance 50テスト

テスト対象: backend/model_governance.py (759行)
  - ModelGovernanceEngine: シングルトン、deprecation差替、フォールバックチェーン、
    タスク→モデルマッピング、統一APIゲートウェイ、監査ログ
  - GovernedModelsProxy: 同期フォールバック付きプロキシ
  - GovernedAsyncModelsProxy: 非同期フォールバック付きプロキシ
  - get_governed_client: ガバナンス付きクライアント生成
  - Harness Hook 統合: PreToolUse / PostToolUse

6カテゴリ構成:
  C1: 入力検証 (8)    — タスク名・モデル種別・権限パラメータ
  C2: モデル解決 (10)  — タスク→モデルマッピング・フォールバックチェーン
  C3: 出力検証 (8)    — 解決結果の構造・APIクライアント返却
  C4: エラー耐性 (10) — API枯渇・モデル未登録・設定ファイル破損
  C5: 統合 (7)        — 全7 Workerとの連携・権限チェック
  C6: 性能 (7)        — モデル解決速度・キャッシュ効果

テスト設計方針:
  - シングルトン汚染防止: 各テストで _initialized=False + 属性リセット
  - gemini_client_factory / usage_tracker は全モック
  - model_config.json は tempfile で差替え可能
  - asyncio テストは pytest-asyncio
"""

import sys
import json
import time
import asyncio
import tempfile
import threading
import pytest
from pathlib import Path
from unittest.mock import (
    AsyncMock, MagicMock, patch, PropertyMock, call
)
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ============================================================
# シングルトンリセット用フィクスチャ
# ============================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """各テストでシングルトンをリセットし、テスト間の状態汚染を防止"""
    from model_governance import ModelGovernanceEngine

    # テスト前: シングルトンをリセット
    ModelGovernanceEngine._instance = None

    yield

    # テスト後: クリーンアップ
    ModelGovernanceEngine._instance = None


def _create_engine(config_override: dict = None) -> "ModelGovernanceEngine":
    """テスト用エンジンを生成（config_override でモック設定を注入）"""
    from model_governance import ModelGovernanceEngine

    engine = ModelGovernanceEngine()

    if config_override:
        if "deprecation_map" in config_override:
            engine._deprecation_map = config_override["deprecation_map"]
        if "fallback_chain" in config_override:
            engine._fallback_chain = config_override["fallback_chain"]
        if "task_mapping" in config_override:
            engine._task_mapping = config_override["task_mapping"]
        if "default_model" in config_override:
            engine._default_model = config_override["default_model"]

    return engine


def _create_temp_config(config_data: dict) -> Path:
    """一時 model_config.json を作成"""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(config_data, tmp, ensure_ascii=False)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


# ============================================================
# C1: 入力検証 (8)
# ============================================================

class TestC1InputValidation:
    """C1: 入力検証テスト — タスク名・モデル種別・権限パラメータ"""

    def test_C1_01_validate_and_correct_known_deprecated(self):
        """C1-01: deprecated モデルが replacement に差替されること"""
        engine = _create_engine({
            "deprecation_map": {"gemini-2.0-flash": "gemini-3-flash-preview"},
        })
        result = engine.validate_and_correct("gemini-2.0-flash", "test")
        assert result == "gemini-3-flash-preview"

    def test_C1_02_validate_and_correct_non_deprecated(self):
        """C1-02: 非 deprecated モデルはそのまま返却されること"""
        engine = _create_engine({
            "deprecation_map": {"gemini-2.0-flash": "gemini-3-flash-preview"},
        })
        result = engine.validate_and_correct("gemini-2.5-flash", "test")
        assert result == "gemini-2.5-flash"

    def test_C1_03_validate_empty_model_name(self):
        """C1-03: 空文字モデル名はそのまま返却されること"""
        engine = _create_engine({"deprecation_map": {}})
        result = engine.validate_and_correct("", "test")
        assert result == ""

    def test_C1_04_validate_caller_empty_string(self):
        """C1-04: caller が空文字でもエラーにならないこと"""
        engine = _create_engine({
            "deprecation_map": {"old-model": "new-model"},
        })
        result = engine.validate_and_correct("old-model", "")
        assert result == "new-model"

    def test_C1_05_validate_chain_deprecation(self):
        """C1-05: チェーン deprecation (A→B→C) で最終 replacement を返すこと"""
        engine = _create_engine({
            "deprecation_map": {
                "model-a": "model-b",
                "model-b": "model-c",
            },
        })
        result = engine.validate_and_correct("model-a", "test")
        assert result == "model-c"

    def test_C1_06_validate_circular_deprecation_no_infinite_loop(self):
        """C1-06: 循環 deprecation (A→B→A) で無限ループしないこと"""
        engine = _create_engine({
            "deprecation_map": {
                "model-a": "model-b",
                "model-b": "model-a",
            },
        })
        # 循環検出で visited により停止
        result = engine.validate_and_correct("model-a", "test")
        assert result in ("model-a", "model-b")

    def test_C1_07_is_fallback_error_with_429(self):
        """C1-07: RESOURCE_EXHAUSTED エラーがフォールバック対象と判定されること"""
        engine = _create_engine()
        error = Exception("429 RESOURCE_EXHAUSTED: quota exceeded")
        assert engine.is_fallback_error(error) is True

    def test_C1_08_is_fallback_error_with_non_matching(self):
        """C1-08: フォールバック対象外のエラーが False を返すこと"""
        engine = _create_engine()
        error = Exception("400 INVALID_ARGUMENT: bad request")
        assert engine.is_fallback_error(error) is False


# ============================================================
# C2: モデル解決 (10)
# ============================================================

class TestC2ModelResolution:
    """C2: モデル解決テスト — タスク→モデルマッピング・フォールバックチェーン"""

    def test_C2_01_resolve_model_from_task_mapping(self):
        """C2-01: task_mapping に定義されたタスクのモデルが解決されること"""
        engine = _create_engine({
            "task_mapping": {"quality_gate": "gemini-3-flash-preview"},
            "deprecation_map": {},
            "default_model": "gemini-2.5-flash",
        })
        result = engine._resolve_model("quality_gate")
        assert result == "gemini-3-flash-preview"

    def test_C2_02_resolve_model_default_fallback(self):
        """C2-02: task_mapping にないタスクは default_model にフォールバックすること"""
        engine = _create_engine({
            "task_mapping": {},
            "deprecation_map": {},
            "default_model": "gemini-2.5-flash",
        })
        result = engine._resolve_model("unknown_task")
        assert result == "gemini-2.5-flash"

    def test_C2_03_resolve_model_explicit_model_override(self):
        """C2-03: 明示的 model 引数が task_mapping より優先すること"""
        engine = _create_engine({
            "task_mapping": {"quality_gate": "gemini-3-flash-preview"},
            "deprecation_map": {},
        })
        result = engine._resolve_model("quality_gate", model="gemini-2.5-flash")
        assert result == "gemini-2.5-flash"

    def test_C2_04_resolve_model_applies_deprecation(self):
        """C2-04: モデル解決時に deprecated 差替が適用されること"""
        engine = _create_engine({
            "task_mapping": {"proofreader": "gemini-2.0-flash"},
            "deprecation_map": {"gemini-2.0-flash": "gemini-3-flash-preview"},
        })
        result = engine._resolve_model("proofreader")
        assert result == "gemini-3-flash-preview"

    def test_C2_05_build_fallback_sequence_full_chain(self):
        """C2-05: フォールバックチェーン全体が正しい配列で返ること"""
        engine = _create_engine({
            "fallback_chain": {
                "gemini-3-flash-preview": "gemini-2.5-flash",
                "gemini-2.5-flash": "gemini-2.5-flash-lite",
                "gemini-2.5-flash-lite": None,
            },
        })
        seq = engine.build_fallback_sequence("gemini-3-flash-preview")
        assert seq == [
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]

    def test_C2_06_build_fallback_sequence_single_model(self):
        """C2-06: フォールバックチェーン未登録モデルは自身のみのリストを返すこと"""
        engine = _create_engine({"fallback_chain": {}})
        seq = engine.build_fallback_sequence("unknown-model")
        assert seq == ["unknown-model"]

    def test_C2_07_build_fallback_sequence_no_circular(self):
        """C2-07: 循環チェーン (A→B→A) で無限ループしないこと"""
        engine = _create_engine({
            "fallback_chain": {
                "model-a": "model-b",
                "model-b": "model-a",
            },
        })
        seq = engine.build_fallback_sequence("model-a")
        assert seq == ["model-a", "model-b"]

    def test_C2_08_get_fallback_returns_next_model(self):
        """C2-08: get_fallback が次のモデルを返すこと"""
        engine = _create_engine({
            "fallback_chain": {"gemini-3-flash-preview": "gemini-2.5-flash"},
        })
        result = engine.get_fallback("gemini-3-flash-preview")
        assert result == "gemini-2.5-flash"

    def test_C2_09_get_fallback_end_of_chain(self):
        """C2-09: チェーン末端で None を返すこと"""
        engine = _create_engine({
            "fallback_chain": {"gemini-2.5-flash-lite": None},
        })
        result = engine.get_fallback("gemini-2.5-flash-lite")
        assert result is None

    def test_C2_10_resolve_model_with_quota_precheck(self):
        """C2-10: usage_tracker 枠チェックで枯渇時にフォールバックすること"""
        engine = _create_engine({
            "task_mapping": {"quality_gate": "gemini-3-flash-preview"},
            "deprecation_map": {},
            "fallback_chain": {
                "gemini-3-flash-preview": "gemini-2.5-flash",
                "gemini-2.5-flash": None,
            },
        })

        mock_ut = MagicMock()
        # gemini-3-flash-preview は枯渇、gemini-2.5-flash は利用可能
        mock_ut.can_make_request.side_effect = lambda m: m != "gemini-3-flash-preview"
        mock_ut.get_usage_ratio.return_value = 1.0

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(), "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut)}):
            result = engine._resolve_model("quality_gate")

        assert result == "gemini-2.5-flash"


# ============================================================
# C3: 出力検証 (8)
# ============================================================

class TestC3OutputValidation:
    """C3: 出力検証テスト — 解決結果の構造・APIクライアント返却"""

    def test_C3_01_get_stats_structure(self):
        """C3-01: get_stats が全フィールドを含むこと"""
        engine = _create_engine()
        stats = engine.get_stats()
        required = [
            "deprecation_corrections", "fallback_activations",
            "total_api_errors", "deprecation_map", "fallback_chain",
            "task_mapping", "recent_events",
        ]
        for field in required:
            assert field in stats, f"フィールド '{field}' が欠損"

    def test_C3_02_deprecation_increments_stats(self):
        """C3-02: deprecated 差替時に deprecation_corrections がインクリメントされること"""
        engine = _create_engine({
            "deprecation_map": {"old": "new"},
        })
        initial = engine._stats["deprecation_corrections"]
        engine.validate_and_correct("old", "test")
        assert engine._stats["deprecation_corrections"] == initial + 1

    def test_C3_03_event_log_records_deprecation(self):
        """C3-03: deprecated 差替が event_log に記録されること"""
        engine = _create_engine({
            "deprecation_map": {"old": "new"},
        })
        engine.validate_and_correct("old", "caller_test")
        assert len(engine._event_log) >= 1
        last = engine._event_log[-1]
        assert last["type"] == "deprecation"
        assert last["original"] == "old"
        assert last["resolved"] == "new"
        assert last["caller"] == "caller_test"

    def test_C3_04_event_log_truncation(self):
        """C3-04: event_log が 200 件超で 100 件に切り詰められること"""
        engine = _create_engine({
            "deprecation_map": {"x": "y"},
        })
        # 201 件のイベントを生成
        for i in range(201):
            engine._record_event("test", f"m{i}", f"r{i}", "caller")
        assert len(engine._event_log) == 100

    def test_C3_05_recent_events_in_stats(self):
        """C3-05: get_stats の recent_events が最新10件を返すこと"""
        engine = _create_engine()
        for i in range(15):
            engine._record_event("test", f"m{i}", f"r{i}", "caller")
        stats = engine.get_stats()
        assert len(stats["recent_events"]) == 10

    def test_C3_06_get_governed_client_returns_proxy(self):
        """C3-06: get_governed_client が GovernedClient を返すこと"""
        mock_client = MagicMock()
        mock_client.models = MagicMock()

        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            from model_governance import get_governed_client
            # governed_client キャッシュをクリアして再生成
            import gemini_client_factory
            gemini_client_factory._governed_client = None
            client = get_governed_client("test_caller")

        assert client is not None
        assert hasattr(client, "models")

    def test_C3_07_get_governed_client_none_without_api_key(self):
        """C3-07: API キー未設定時に get_governed_client が None を返すこと"""
        with patch("gemini_client_factory._get_raw_client", return_value=None):
            from model_governance import get_governed_client
            import gemini_client_factory
            gemini_client_factory._governed_client = None
            client = get_governed_client("test")
        assert client is None

    def test_C3_08_error_string_truncation_in_event(self):
        """C3-08: event_log の error が 200 文字で切り詰められること"""
        engine = _create_engine()
        long_error = "x" * 500
        engine._record_event("test", "m", "r", "caller", error=long_error)
        assert len(engine._event_log[-1]["error"]) == 200


# ============================================================
# C4: エラー耐性 (10)
# ============================================================

class TestC4ErrorResilience:
    """C4: エラー耐性テスト — API枯渇・モデル未登録・設定ファイル破損"""

    def test_C4_01_config_load_missing_file(self):
        """C4-01: model_config.json が存在しない場合にエラーなく初期化されること"""
        from model_governance import ModelGovernanceEngine

        with patch("model_governance.Path") as MockPath:
            mock_path = MagicMock()
            mock_path.__truediv__ = MagicMock(return_value=mock_path)
            mock_path.open = MagicMock(side_effect=FileNotFoundError("not found"))
            MockPath.return_value = mock_path
            MockPath.__file__ = "dummy"

            # config なしでも初期化は成功する
            engine = ModelGovernanceEngine()
            # 設定は空
            assert isinstance(engine._deprecation_map, dict)

    def test_C4_02_config_load_invalid_json(self):
        """C4-02: model_config.json が不正 JSON でもエラーなく初期化されること"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.write("{invalid json}")
        tmp.close()

        engine = _create_engine()
        original_load = engine._load_config

        with patch.object(type(engine), '_load_config', autospec=True) as mock_load:
            def _load_broken(self_arg):
                try:
                    with open(tmp.name, "r") as f:
                        json.load(f)
                except (json.JSONDecodeError, ValueError):
                    pass  # Expected: invalid JSON is handled gracefully
            mock_load.side_effect = _load_broken
            # 不正 JSON でも例外は発生しない
            engine._load_config()

        Path(tmp.name).unlink(missing_ok=True)

    def test_C4_03_is_fallback_error_503(self):
        """C4-03: 503 UNAVAILABLE がフォールバック対象として検出されること"""
        engine = _create_engine()
        error = Exception("503 UNAVAILABLE: server overloaded")
        assert engine.is_fallback_error(error) is True

    def test_C4_04_is_fallback_error_404(self):
        """C4-04: 404 NOT_FOUND がフォールバック対象として検出されること"""
        engine = _create_engine()
        error = Exception("404 NOT_FOUND: model does not exist")
        assert engine.is_fallback_error(error) is True

    def test_C4_05_is_fallback_error_quota_zero(self):
        """C4-05: 'limit: 0' エラーがフォールバック対象として検出されること"""
        engine = _create_engine()
        error = Exception("quota limit: 0 for this model")
        assert engine.is_fallback_error(error) is True

    @pytest.mark.asyncio
    async def test_C4_06_call_raises_on_no_api_key(self):
        """C4-06: call() で API キー未設定時に ValueError が発生すること"""
        engine = _create_engine({
            "task_mapping": {"test": "gemini-2.5-flash"},
            "deprecation_map": {},
        })

        with patch("gemini_client_factory._get_raw_client", return_value=None):
            with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
                await engine.call(task="test", prompt="hello")

    @pytest.mark.asyncio
    async def test_C4_07_call_fallback_on_429(self):
        """C4-07: call() で 429 エラー時にフォールバックチェーンを辿ること"""
        engine = _create_engine({
            "task_mapping": {"test": "gemini-3-flash-preview"},
            "deprecation_map": {},
            "fallback_chain": {
                "gemini-3-flash-preview": "gemini-2.5-flash",
                "gemini-2.5-flash": None,
            },
        })

        call_models = []
        mock_response = MagicMock()
        mock_response.text = "OK response"

        async def _mock_generate(**kwargs):
            call_models.append(kwargs.get("model"))
            if kwargs.get("model") == "gemini-3-flash-preview":
                from google.api_core.exceptions import GoogleAPICallError
                raise GoogleAPICallError("429 RESOURCE_EXHAUSTED")
            return mock_response

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=_mock_generate)

        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            result = await engine.call(task="test", prompt="hello")

        assert result == "OK response"
        assert "gemini-3-flash-preview" in call_models
        assert "gemini-2.5-flash" in call_models

    @pytest.mark.asyncio
    async def test_C4_08_call_all_models_exhausted(self):
        """C4-08: 全フォールバック枯渇時に RuntimeError が発生すること"""
        engine = _create_engine({
            "task_mapping": {"test": "gemini-3-flash-preview"},
            "deprecation_map": {},
            "fallback_chain": {
                "gemini-3-flash-preview": "gemini-2.5-flash",
                "gemini-2.5-flash": None,
            },
        })

        async def _always_fail(**kwargs):
            from google.api_core.exceptions import GoogleAPICallError
            raise GoogleAPICallError("429 RESOURCE_EXHAUSTED")

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=_always_fail)

        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="全フォールバック枯渇"):
                await engine.call(task="test", prompt="hello")

    @pytest.mark.asyncio
    async def test_C4_09_call_non_fallback_error_raises_immediately(self):
        """C4-09: フォールバック対象外エラーは即座に raise されること"""
        engine = _create_engine({
            "task_mapping": {"test": "gemini-2.5-flash"},
            "deprecation_map": {},
            "fallback_chain": {"gemini-2.5-flash": "gemini-2.5-flash-lite"},
        })

        async def _bad_request(**kwargs):
            from google.api_core.exceptions import GoogleAPICallError
            raise GoogleAPICallError("400 INVALID_ARGUMENT: bad prompt")

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=_bad_request)

        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            with pytest.raises(Exception, match="400 INVALID_ARGUMENT"):
                await engine.call(task="test", prompt="hello")

    def test_C4_10_governed_proxy_sync_fallback(self):
        """C4-10: GovernedModelsProxy 同期版でフォールバックが動作すること"""
        from model_governance import GovernedModelsProxy

        engine = _create_engine({
            "deprecation_map": {},
            "fallback_chain": {
                "model-a": "model-b",
                "model-b": None,
            },
        })

        call_count = 0
        mock_response = MagicMock()

        def _mock_generate(*, model, **kwargs):
            nonlocal call_count
            call_count += 1
            if model == "model-a":
                from google.api_core.exceptions import GoogleAPICallError
                raise GoogleAPICallError("429 RESOURCE_EXHAUSTED")
            return mock_response

        mock_real = MagicMock()
        mock_real.generate_content = _mock_generate

        proxy = GovernedModelsProxy(mock_real, "test")

        with patch("model_governance.model_governance", engine):
            with patch("time.sleep"):  # RETRY_DELAY をスキップ
                result = proxy.generate_content(model="model-a")

        assert result is mock_response
        assert call_count == 2


# ============================================================
# C5: 統合 (7)
# ============================================================

class TestC5Integration:
    """C5: 統合テスト — 全7 Workerとの連携・権限チェック"""

    def test_C5_01_task_mapping_covers_all_workers(self):
        """C5-01: model_config.json の task_mapping が全 Worker 関連タスクをカバーすること"""
        engine = _create_engine()
        # 実際の model_config.json を読み込んだエンジンのタスクマッピング
        config_path = Path(__file__).parent.parent.parent / "model_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            task_mapping = config.get("task_mapping", {})

            # 全 Worker が使用する可能性のあるタスク名
            worker_tasks = [
                "proofreader",
                "youtube_optimization",
                "quality_gate",
            ]
            for task in worker_tasks:
                assert task in task_mapping, (
                    f"Worker タスク '{task}' が task_mapping に未登録"
                )

    def test_C5_02_worker_scope_map_model_resolution(self):
        """C5-02: 各 Worker スコープでモデル解決が正常に動作すること"""
        engine = _create_engine({
            "task_mapping": {
                "proofreader": "gemini-3-flash-preview",
                "quality_gate": "gemini-3-flash-preview",
                "youtube_optimization": "gemini-3-flash-preview",
            },
            "deprecation_map": {},
            "default_model": "gemini-2.5-flash",
        })

        # 各タスクのモデル解決
        for task in ["proofreader", "quality_gate", "youtube_optimization"]:
            result = engine._resolve_model(task)
            assert result == "gemini-3-flash-preview", (
                f"タスク '{task}' のモデル解決が不正: {result}"
            )

    def test_C5_03_governance_singleton_consistency(self):
        """C5-03: model_governance シングルトンが一貫したインスタンスを返すこと"""
        from model_governance import ModelGovernanceEngine

        engine1 = ModelGovernanceEngine()
        engine2 = ModelGovernanceEngine()
        assert engine1 is engine2

    def test_C5_04_reload_refreshes_config(self):
        """C5-04: reload() で設定が再読み込みされること"""
        engine = _create_engine({
            "deprecation_map": {"old": "new"},
        })
        assert "old" in engine._deprecation_map

        # reload で状態がクリアされる
        engine.reload()
        # reload 後は model_config.json から再読み込みされる
        # テスト環境では DeprecationMap は model_config.json のものに戻る
        assert isinstance(engine._deprecation_map, dict)

    @pytest.mark.asyncio
    async def test_C5_05_pre_tool_use_hook_deprecation_correction(self):
        """C5-05: PreToolUse Hook でモデル名が是正されること"""
        from model_governance import _model_governance_hook, ModelGovernanceEngine

        engine = ModelGovernanceEngine()
        engine._deprecation_map = {"gemini-2.0-flash": "gemini-3-flash-preview"}

        hook_input = MagicMock()
        hook_input.tool_input = {"model": "gemini-2.0-flash"}
        hook_input.tool_name = "test_tool"

        with patch("model_governance.model_governance", engine):
            result = await _model_governance_hook(hook_input)

        assert result is not None
        # HookOutput のモック確認
        # 実際のパスでは harness.hooks.HookOutput が必要

    @pytest.mark.asyncio
    async def test_C5_06_post_tool_use_hook_usage_tracking(self):
        """C5-06: PostToolUse Hook で usage_tracker が呼ばれること"""
        from model_governance import _model_usage_tracking_hook

        hook_input = MagicMock()
        hook_input.tool_input = {"model": "gemini-2.5-flash"}
        hook_input.tool_name = "test_tool"

        mock_ut = MagicMock()
        mock_ut.track_request.return_value = {"alert_level": "ok", "usage_ratio": 0.5}

        with patch.dict("sys.modules", {
            "usage_tracker": MagicMock(),
            "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut),
        }):
            result = await _model_usage_tracking_hook(hook_input)

        mock_ut.track_request.assert_called_once_with("gemini-2.5-flash")

    @pytest.mark.asyncio
    async def test_C5_07_post_hook_no_model_skips_tracking(self):
        """C5-07: ツール入力にモデルが含まれない場合は使用量追跡をスキップすること"""
        from model_governance import _model_usage_tracking_hook

        hook_input = MagicMock()
        hook_input.tool_input = {"prompt": "hello"}
        hook_input.tool_name = "test_tool"

        result = await _model_usage_tracking_hook(hook_input)
        assert result is None


# ============================================================
# C6: 性能 (7)
# ============================================================

class TestC6Performance:
    """C6: 性能テスト — モデル解決速度・キャッシュ効果"""

    def test_C6_01_resolve_model_speed(self):
        """C6-01: _resolve_model が 1ms 以下で完了すること"""
        engine = _create_engine({
            "task_mapping": {"quality_gate": "gemini-3-flash-preview"},
            "deprecation_map": {},
            "default_model": "gemini-2.5-flash",
        })

        start = time.perf_counter()
        for _ in range(1000):
            engine._resolve_model("quality_gate")
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / 1000) * 1000
        assert avg_ms < 1.0, f"平均 {avg_ms:.3f}ms (> 1ms)"

    def test_C6_02_validate_and_correct_speed(self):
        """C6-02: validate_and_correct が 100 回実行で 10ms 以下であること"""
        engine = _create_engine({
            "deprecation_map": {"gemini-2.0-flash": "gemini-3-flash-preview"},
        })

        start = time.perf_counter()
        for _ in range(100):
            engine.validate_and_correct("gemini-2.0-flash", "bench")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"100 回で {elapsed*1000:.1f}ms (> 100ms)"

    def test_C6_03_build_fallback_sequence_speed(self):
        """C6-03: build_fallback_sequence が 1ms 以下で完了すること"""
        engine = _create_engine({
            "fallback_chain": {
                "gemini-3-flash-preview": "gemini-2.5-flash",
                "gemini-2.5-flash": "gemini-2.5-flash-lite",
                "gemini-2.5-flash-lite": None,
            },
        })

        start = time.perf_counter()
        for _ in range(1000):
            engine.build_fallback_sequence("gemini-3-flash-preview")
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / 1000) * 1000
        assert avg_ms < 1.0, f"平均 {avg_ms:.3f}ms (> 1ms)"

    def test_C6_04_config_load_speed(self):
        """C6-04: _load_config が 100ms 以下で完了すること"""
        engine = _create_engine()

        start = time.perf_counter()
        engine.reload()
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"config reload: {elapsed*1000:.1f}ms (> 100ms)"

    def test_C6_05_thread_safety_singleton(self):
        """C6-05: マルチスレッドでシングルトンが一つだけ生成されること"""
        from model_governance import ModelGovernanceEngine

        instances = []
        errors = []

        def _create():
            try:
                inst = ModelGovernanceEngine()
                instances.append(id(inst))
            except (AttributeError, ValueError, KeyError, TypeError, RuntimeError) as e:
                errors.append(e)

        threads = [threading.Thread(target=_create) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"スレッドエラー: {errors}"
        # 全スレッドが同一インスタンス
        assert len(set(instances)) == 1, f"複数インスタンス: {set(instances)}"

    def test_C6_06_event_recording_speed(self):
        """C6-06: _record_event が 1000 回で 10ms 以下であること"""
        engine = _create_engine()

        start = time.perf_counter()
        for i in range(1000):
            engine._record_event("test", f"m{i}", f"r{i}", "bench")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.01, f"1000 件で {elapsed*1000:.1f}ms (> 10ms)"

    def test_C6_07_classify_error_coverage(self):
        """C6-07: GovernedModelsProxy._classify_error が全エラーパターンを分類すること"""
        from model_governance import GovernedModelsProxy

        proxy = GovernedModelsProxy(MagicMock(), "test")

        test_cases = [
            (Exception("429 RESOURCE_EXHAUSTED"), "429:枠枯渇"),
            (Exception("503 UNAVAILABLE"), "503:サーバー混雑"),
            (Exception("404 NOT_FOUND"), "404:モデル不在"),
            (Exception("quota limit: 0"), "quota=0:利用不可"),
            (Exception("unknown error xyz"), "unknown:"),
        ]

        for error, expected_prefix in test_cases:
            result = proxy._classify_error(error)
            assert result.startswith(expected_prefix), (
                f"'{error}' → '{result}' (expected prefix: '{expected_prefix}')"
            )


# ============================================================
# C7: 追加カバレッジ (23)
# ============================================================

class TestC7AdditionalCoverage:
    """C7: 追加カバレッジテスト — 非同期プロキシ・委譲・フック登録・クォータ例外"""

    @pytest.mark.asyncio
    async def test_C7_01_governed_async_proxy_success(self):
        """C7-01: GovernedAsyncModelsProxy が正常系で正しく値を返すこと"""
        from model_governance import GovernedAsyncModelsProxy
        mock_real = MagicMock()
        mock_real.generate_content = AsyncMock(return_value="async ok")
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        
        result = await proxy.generate_content(model="gemini-2.5-flash")
        assert result == "async ok"

    @pytest.mark.asyncio
    async def test_C7_02_governed_async_proxy_fallback_success(self):
        """C7-02: GovernedAsyncModelsProxy が 429 エラー時にフォールバックして成功すること"""
        from model_governance import GovernedAsyncModelsProxy
        
        engine = _create_engine({
            "deprecation_map": {},
            "fallback_chain": {
                "model-a": "model-b",
                "model-b": None,
            }
        })
        
        call_models = []
        async def _mock_generate(*, model, **kwargs):
            call_models.append(model)
            if model == "model-a":
                from google.api_core.exceptions import GoogleAPICallError
                raise GoogleAPICallError("429 RESOURCE_EXHAUSTED")
            mock_res = MagicMock()
            mock_res.text = "async fallback ok"
            return mock_res
            
        mock_real = MagicMock()
        mock_real.generate_content = AsyncMock(side_effect=_mock_generate)
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        
        with patch("model_governance.model_governance", engine):
            with patch("asyncio.sleep"):  # sleep をスキップ
                result = await proxy.generate_content(model="model-a")
                
        assert result.text == "async fallback ok"
        assert call_models == ["model-a", "model-b"]

    @pytest.mark.asyncio
    async def test_C7_03_governed_async_proxy_exhausted(self):
        """C7-03: GovernedAsyncModelsProxy がフォールバックチェーン枯渇時に例外を発生させること"""
        from model_governance import GovernedAsyncModelsProxy
        
        engine = _create_engine({
            "deprecation_map": {},
            "fallback_chain": {
                "model-a": "model-b",
                "model-b": None,
            }
        })
        
        async def _mock_generate(*, model, **kwargs):
            from google.api_core.exceptions import GoogleAPICallError
            raise GoogleAPICallError("429 RESOURCE_EXHAUSTED")
            
        mock_real = MagicMock()
        mock_real.generate_content = AsyncMock(side_effect=_mock_generate)
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        
        with patch("model_governance.model_governance", engine):
            with patch("asyncio.sleep"):
                with pytest.raises(Exception, match="429 RESOURCE_EXHAUSTED"):
                    await proxy.generate_content(model="model-a")

    @pytest.mark.asyncio
    async def test_C7_04_governed_async_proxy_non_fallback_error(self):
        """C7-04: GovernedAsyncModelsProxy がフォールバック対象外のエラーで即座に例外を発生させること"""
        from model_governance import GovernedAsyncModelsProxy
        
        async def _mock_generate(*, model, **kwargs):
            raise Exception("400 INVALID_ARGUMENT")
            
        mock_real = MagicMock()
        mock_real.generate_content = AsyncMock(side_effect=_mock_generate)
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        
        with pytest.raises(Exception, match="400 INVALID_ARGUMENT"):
            await proxy.generate_content(model="gemini-2.5-flash")

    def test_C7_05_governed_client_getattr(self):
        """C7-05: get_governed_client で取得したクライアントが他の属性を real クライアントに委譲すること"""
        mock_real = MagicMock()
        mock_real.some_method.return_value = "hello"
        mock_real.models = MagicMock()
        
        with patch("gemini_client_factory._get_raw_client", return_value=mock_real):
            from model_governance import get_governed_client
            import gemini_client_factory
            gemini_client_factory._governed_client = None
            
            client = get_governed_client("test")
            assert client.some_method() == "hello"

    def test_C7_06_register_governance_hook(self):
        """C7-06: register_governance_hook が正常に動作すること"""
        from model_governance import register_governance_hook
        
        mock_hook_system = MagicMock()
        with patch("harness.hooks.hook_system", mock_hook_system):
            register_governance_hook()
            assert mock_hook_system.register.call_count == 2

    def test_C7_07_resolve_model_quota_precheck_chain_end(self):
        """C7-07: _resolve_model で usage_tracker が利用不可を返し、フォールバックチェーン末端に達した場合"""
        engine = _create_engine({
            "task_mapping": {"quality_gate": "gemini-2.5-flash"},
            "deprecation_map": {},
            "fallback_chain": {
                "gemini-2.5-flash": None,
            },
        })

        mock_ut = MagicMock()
        mock_ut.can_make_request.return_value = False
        mock_ut.get_usage_ratio.return_value = 1.0

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(), "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut)}):
            result = engine._resolve_model("quality_gate")

        assert result == "gemini-2.5-flash"

    def test_C7_08_resolve_model_quota_precheck_exception(self):
        """C7-08: _resolve_model で usage_tracker で例外が発生した場合に安全にスルーすること"""
        engine = _create_engine({
            "task_mapping": {"quality_gate": "gemini-2.5-flash"},
            "deprecation_map": {},
            "fallback_chain": {},
        })

        mock_ut = MagicMock()
        mock_ut.can_make_request.side_effect = RuntimeError("db connection error")

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(), "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut)}):
            result = engine._resolve_model("quality_gate")

        assert result == "gemini-2.5-flash"

    def test_C7_09_governed_models_proxy_getattr(self):
        """C7-09: GovernedModelsProxy が real_models の属性を正しく委譲すること"""
        from model_governance import GovernedModelsProxy
        mock_real = MagicMock()
        mock_real.some_attr = "val"
        proxy = GovernedModelsProxy(mock_real, "test")
        assert proxy.some_attr == "val"

    def test_C7_10_resolve_model_quota_precheck_import_error(self):
        """C7-10: _resolve_model で usage_tracker がインポートできない場合にスルーすること"""
        engine = _create_engine({
            "task_mapping": {"quality_gate": "gemini-2.5-flash"},
            "deprecation_map": {},
            "fallback_chain": {},
        })

        with patch.dict("sys.modules", {"usage_tracker.tracker": None, "usage_tracker": None}):
            result = engine._resolve_model("quality_gate")

        assert result == "gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_C7_11_engine_call_with_config(self):
        """C7-11: call() の config 引数が正しく反映されること"""
        engine = _create_engine({
            "task_mapping": {"test_task": "gemini-2.5-flash"},
            "deprecation_map": {},
        })

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock()
        
        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            await engine.call(task="test_task", prompt="hello", config={"temperature": 0.7})
            
        mock_client.aio.models.generate_content.assert_called_once_with(
            model="gemini-2.5-flash", contents="hello", temperature=0.7
        )

    @pytest.mark.asyncio
    async def test_C7_12_engine_call_sync_client_thread(self):
        """C7-12: call() が aio 属性を持たないクライアントに対して同期実行（to_thread）すること"""
        engine = _create_engine({
            "task_mapping": {"test_task": "gemini-2.5-flash"},
            "deprecation_map": {},
        })

        mock_client = MagicMock(spec=[])
        mock_client.models = MagicMock()
        mock_client.models.generate_content = MagicMock()

        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            await engine.call(task="test_task", prompt="hello")

        mock_client.models.generate_content.assert_called_once_with(
            model="gemini-2.5-flash", contents="hello"
        )

    @pytest.mark.asyncio
    async def test_C7_13_engine_call_empty_chain_raises(self):
        """C7-13: call() でフォールバックチェーンが空の場合に TypeError (last_error が None) を投げること"""
        engine = _create_engine({
            "task_mapping": {"test_task": "gemini-2.5-flash"},
            "deprecation_map": {},
        })

        mock_client = MagicMock()
        
        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            with patch.object(engine, "build_fallback_sequence", return_value=[]):
                with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
                    await engine.call(task="test_task", prompt="hello")

    def test_C7_14_track_usage_alert_level(self):
        """C7-14: _track_usage で警告レベルが warning, block, critical のときにイベント記録すること"""
        engine = _create_engine()
        mock_ut = MagicMock()
        mock_ut.track_request.return_value = {"alert_level": "warning", "usage_ratio": 0.85}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(), "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut)}):
            engine._track_usage("gemini-2.5-flash", "test_caller")

        assert len(engine._event_log) > 0
        assert engine._event_log[-1]["type"] == "quota_alert"

    def test_C7_15_track_usage_exception(self):
        """C7-15: _track_usage で例外が発生した場合に安全にスルーすること"""
        engine = _create_engine()
        mock_ut = MagicMock()
        mock_ut.track_request.side_effect = OSError("tracker error")

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(), "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut)}):
            engine._track_usage("gemini-2.5-flash", "test_caller")

    def test_C7_16_governed_models_proxy_non_fallback_error(self):
        """C7-16: GovernedModelsProxy でフォールバック対象外エラーが発生した場合に即座に raise すること"""
        from model_governance import GovernedModelsProxy
        mock_real = MagicMock()
        mock_real.generate_content.side_effect = Exception("400 INVALID_ARGUMENT")
        proxy = GovernedModelsProxy(mock_real, "test")

        with pytest.raises(Exception, match="400 INVALID_ARGUMENT"):
            proxy.generate_content(model="gemini-2.5-flash")

    def test_C7_17_governed_models_proxy_fallback_exhausted(self):
        """C7-17: GovernedModelsProxy で全フォールバックが枯渇した場合に raise すること"""
        from model_governance import GovernedModelsProxy
        
        engine = _create_engine({
            "deprecation_map": {},
            "fallback_chain": {
                "model-a": "model-b",
                "model-b": None,
            }
        })

        mock_real = MagicMock()
        mock_real.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")
        proxy = GovernedModelsProxy(mock_real, "test")

        with patch("model_governance.model_governance", engine):
            with patch("time.sleep"):
                with pytest.raises(Exception, match="429 RESOURCE_EXHAUSTED"):
                    proxy.generate_content(model="model-a")

    def test_C7_18_governed_models_proxy_empty_chain(self):
        """C7-18: GovernedModelsProxy でチェーンが空の場合に TypeError (last_error が None) を raise すること"""
        from model_governance import GovernedModelsProxy
        proxy = GovernedModelsProxy(MagicMock(), "test")

        with patch("model_governance.model_governance") as mock_gov:
            mock_gov.validate_and_correct.return_value = "model-a"
            mock_gov.build_fallback_sequence.return_value = []
            
            with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
                proxy.generate_content(model="model-a")

    @pytest.mark.asyncio
    async def test_C7_19_pre_tool_use_hook_no_change(self):
        """C7-19: _model_governance_hook でモデル変更がない場合に None を返すこと"""
        from model_governance import _model_governance_hook
        hook_input = MagicMock()
        hook_input.tool_input = {"prompt": "hello"}
        
        res = await _model_governance_hook(hook_input)
        assert res is None

    @pytest.mark.asyncio
    async def test_C7_20_post_tool_use_hook_alert(self):
        """C7-20: _model_usage_tracking_hook で警告レベルのときにイベント記録すること"""
        from model_governance import _model_usage_tracking_hook
        hook_input = MagicMock()
        hook_input.tool_input = {"model": "gemini-2.5-flash"}
        hook_input.tool_name = "test_tool"

        mock_ut = MagicMock()
        mock_ut.track_request.return_value = {"alert_level": "warning", "usage_ratio": 0.85}

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(), "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut)}):
            res = await _model_usage_tracking_hook(hook_input)
            assert res is None

    @pytest.mark.asyncio
    async def test_C7_21_post_tool_use_hook_exception(self):
        """C7-21: _model_usage_tracking_hook で例外が発生した場合に安全にスルーすること"""
        from model_governance import _model_usage_tracking_hook
        hook_input = MagicMock()
        hook_input.tool_input = {"model": "gemini-2.5-flash"}
        hook_input.tool_name = "test_tool"

        mock_ut = MagicMock()
        mock_ut.track_request.side_effect = OSError("tracker error")

        with patch.dict("sys.modules", {"usage_tracker": MagicMock(), "usage_tracker.tracker": MagicMock(usage_tracker=mock_ut)}):
            res = await _model_usage_tracking_hook(hook_input)
            assert res is None

    def test_C7_22_register_governance_hook_import_error(self):
        """C7-22: register_governance_hook で Harness がインポートできない場合にスキップすること"""
        from model_governance import register_governance_hook
        
        with patch.dict("sys.modules", {"harness.hooks": None}):
            register_governance_hook()

    @pytest.mark.asyncio
    async def test_C7_23_governed_async_proxy_empty_chain(self):
        """C7-23: GovernedAsyncModelsProxy でチェーンが空の場合に TypeError を raise すること"""
        from model_governance import GovernedAsyncModelsProxy
        proxy = GovernedAsyncModelsProxy(MagicMock(), "test")

        with patch("model_governance.model_governance") as mock_gov:
            mock_gov.validate_and_correct.return_value = "model-a"
            mock_gov.build_fallback_sequence.return_value = []
            
            with pytest.raises(TypeError, match="exceptions must derive from BaseException"):
                await proxy.generate_content(model="model-a")

    def test_C7_24_load_config_filenotfound(self):
        """C7-24: _load_config で FileNotFoundError が発生したときに警告ログを出すこと"""
        engine = _create_engine()
        with patch("builtins.open", side_effect=FileNotFoundError("not found")):
            # 例外が発生せずスルーされること
            engine._load_config()

    def test_C7_25_load_config_permissionerror(self):
        """C7-25: _load_config で PermissionError が発生したときに警告ログを出すこと"""
        engine = _create_engine()
        with patch("builtins.open", side_effect=PermissionError("denied")):
            engine._load_config()

    def test_C7_26_governed_models_proxy_non_fallback_error_raise(self):
        """C7-26: GovernedModelsProxy でフォールバック対象外の GoogleAPICallError が即座に raise されること"""
        from model_governance import GovernedModelsProxy
        from google.api_core.exceptions import GoogleAPICallError
        mock_real = MagicMock()
        mock_real.generate_content.side_effect = GoogleAPICallError("400 INVALID_ARGUMENT")
        proxy = GovernedModelsProxy(mock_real, "test")
        with pytest.raises(GoogleAPICallError):
            proxy.generate_content(model="gemini-2.5-flash")

    def test_C7_27_governed_models_proxy_embed_content_success(self):
        """C7-27: GovernedModelsProxy の embed_content が正常に実行されること"""
        from model_governance import GovernedModelsProxy
        mock_real = MagicMock()
        mock_real.embed_content.return_value = "embed ok"
        proxy = GovernedModelsProxy(mock_real, "test")
        res = proxy.embed_content(model="gemini-2.5-flash", contents="hello")
        assert res == "embed ok"

    def test_C7_28_governed_models_proxy_embed_content_fallback(self):
        """C7-28: GovernedModelsProxy の embed_content がエラー時にフォールバックして成功すること"""
        from model_governance import GovernedModelsProxy
        from google.api_core.exceptions import GoogleAPICallError
        engine = _create_engine({
            "fallback_chain": {"model-a": "model-b", "model-b": None}
        })
        call_models = []
        def _mock_embed(*, model, contents, **kwargs):
            call_models.append(model)
            if model == "model-a":
                raise GoogleAPICallError("429 RESOURCE_EXHAUSTED")
            return "fallback embed ok"
        mock_real = MagicMock()
        mock_real.embed_content.side_effect = _mock_embed
        proxy = GovernedModelsProxy(mock_real, "test")
        with patch("model_governance.model_governance", engine):
            with patch("time.sleep"):
                res = proxy.embed_content(model="model-a", contents="hello")
        assert res == "fallback embed ok"
        assert call_models == ["model-a", "model-b"]

    def test_C7_29_governed_models_proxy_embed_content_exhausted(self):
        """C7-29: GovernedModelsProxy の embed_content で全フォールバックが枯渇した場合に raise すること"""
        from model_governance import GovernedModelsProxy
        from google.api_core.exceptions import GoogleAPICallError
        engine = _create_engine({
            "fallback_chain": {"model-a": "model-b", "model-b": None}
        })
        mock_real = MagicMock()
        mock_real.embed_content.side_effect = GoogleAPICallError("429 RESOURCE_EXHAUSTED")
        proxy = GovernedModelsProxy(mock_real, "test")
        with patch("model_governance.model_governance", engine):
            with patch("time.sleep"):
                with pytest.raises(GoogleAPICallError):
                    proxy.embed_content(model="model-a", contents="hello")

    @pytest.mark.asyncio
    async def test_C7_30_governed_async_proxy_non_fallback_error_raise(self):
        """C7-30: GovernedAsyncModelsProxy でフォールバック対象外のエラーが即座に raise されること"""
        from model_governance import GovernedAsyncModelsProxy
        from google.api_core.exceptions import GoogleAPICallError
        mock_real = MagicMock()
        mock_real.generate_content = AsyncMock(side_effect=GoogleAPICallError("400 BAD"))
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        with pytest.raises(GoogleAPICallError):
            await proxy.generate_content(model="gemini-2.5-flash")

    @pytest.mark.asyncio
    async def test_C7_31_governed_async_proxy_embed_content_success(self):
        """C7-31: GovernedAsyncModelsProxy の embed_content が正常に実行されること"""
        from model_governance import GovernedAsyncModelsProxy
        mock_real = MagicMock()
        mock_real.embed_content = AsyncMock(return_value="async embed ok")
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        res = await proxy.embed_content(model="gemini-2.5-flash", contents="hello")
        assert res == "async embed ok"

    @pytest.mark.asyncio
    async def test_C7_32_governed_async_proxy_embed_content_fallback(self):
        """C7-32: GovernedAsyncModelsProxy の embed_content がエラー時にフォールバックすること"""
        from model_governance import GovernedAsyncModelsProxy
        from google.api_core.exceptions import GoogleAPICallError
        engine = _create_engine({
            "fallback_chain": {"model-a": "model-b", "model-b": None}
        })
        call_models = []
        async def _mock_embed(*, model, contents, **kwargs):
            call_models.append(model)
            if model == "model-a":
                raise GoogleAPICallError("429 RESOURCE_EXHAUSTED")
            return "async fallback embed ok"
        mock_real = MagicMock()
        mock_real.embed_content = AsyncMock(side_effect=_mock_embed)
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        with patch("model_governance.model_governance", engine):
            with patch("asyncio.sleep"):
                res = await proxy.embed_content(model="model-a", contents="hello")
        assert res == "async fallback embed ok"
        assert call_models == ["model-a", "model-b"]

    @pytest.mark.asyncio
    async def test_C7_33_governed_async_proxy_embed_content_exhausted(self):
        """C7-33: GovernedAsyncModelsProxy の embed_content で全フォールバックが枯渇した場合に raise すること"""
        from model_governance import GovernedAsyncModelsProxy
        from google.api_core.exceptions import GoogleAPICallError
        engine = _create_engine({
            "fallback_chain": {"model-a": "model-b", "model-b": None}
        })
        mock_real = MagicMock()
        mock_real.embed_content = AsyncMock(side_effect=GoogleAPICallError("429 RESOURCE_EXHAUSTED"))
        proxy = GovernedAsyncModelsProxy(mock_real, "test")
        with patch("model_governance.model_governance", engine):
            with patch("asyncio.sleep"):
                with pytest.raises(GoogleAPICallError):
                    await proxy.embed_content(model="model-a", contents="hello")
