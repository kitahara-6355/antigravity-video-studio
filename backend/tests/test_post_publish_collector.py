import pytest
import os
import sys
import asyncio
from unittest.mock import patch

# 絶対パスでワークスペースの backend を追加
# Dynamic path injection
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from services.post_publish_collector import (
    PostPublishCollector,
    post_publish_collector,
    PostPublishCollectorError,
    PostPublishCollectorValueError,
    PostPublishCollectorTypeError,
    PostPublishCollectorNotImplementedError,
    PostPublishCollectorAPIError,
    PostPublishCollectorNetworkError,
    PostPublishCollectorAuthError,
    PostPublishCollectorQuotaError,
    PostPublishCollectorNotFoundError,
)



class TestPostPublishCollectorDirect:
    """post_publish_collector.py のテストカバレッジを100%にするための詳細テスト"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        # シングルトンのAPIモードと環境変数を保存
        original_override = post_publish_collector._api_mode_override
        original_env = os.environ.get("YOUTUBE_API_MODE")
        yield
        # 元の状態に戻す
        post_publish_collector._api_mode_override = original_override
        if original_env is not None:
            os.environ["YOUTUBE_API_MODE"] = original_env
        elif "YOUTUBE_API_MODE" in os.environ:
            del os.environ["YOUTUBE_API_MODE"]

    def test_singleton_instance(self):
        """シングルトンインスタンスが正しく初期化されていること"""
        assert isinstance(post_publish_collector, PostPublishCollector)

    @pytest.mark.asyncio
    async def test_mock_mode_behavior(self):
        """mock モードの決定論的データ生成を検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        result1 = await collector.collect_performance_data("vid_001", elapsed_hours=24)
        result2 = await collector.collect_performance_data("vid_001", elapsed_hours=24)
        
        # 決定論的データであることを確認
        assert result1["metrics"]["views"] == result2["metrics"]["views"]
        assert result1["metrics"]["click_through_rate"] == result2["metrics"]["click_through_rate"]
        assert result1["metrics"]["retention_rate_pct"] == result2["metrics"]["retention_rate_pct"]
        assert result1["video_id"] == "vid_001"
        assert result1["is_mock"] is True

    @pytest.mark.asyncio
    async def test_real_mode_raises_not_implemented(self):
        """real モードでは NotImplementedError が発生すること"""
        collector = PostPublishCollector()
        collector.api_mode = "real"
        
        with pytest.raises(NotImplementedError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=24)
        
        assert "YouTube Analytics API の本番統合は未実装です" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_different_video_ids_produce_different_data(self):
        """異なる video_id に対して異なるデータが生成されること"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        result1 = await collector.collect_performance_data("vid_aaa", elapsed_hours=24)
        result2 = await collector.collect_performance_data("vid_bbb", elapsed_hours=24)
        
        views_differ = result1["metrics"]["views"] != result2["metrics"]["views"]
        ctr_differ = result1["metrics"]["click_through_rate"] != result2["metrics"]["click_through_rate"]
        assert views_differ or ctr_differ

    @pytest.mark.asyncio
    async def test_boundary_elapsed_hours(self):
        """経過時間の境界値テスト（0, 非常に大きな値）"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        # elapsed_hours = 0
        result_zero = await collector.collect_performance_data("vid_001", elapsed_hours=0)
        assert result_zero["elapsed_hours"] == 0
        assert "views" in result_zero["metrics"]
        
        # 負数の場合は ValueError
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=-24)
        assert "must be non-negative" in str(excinfo.value)
        
        # elapsed_hours = 999999
        result_large = await collector.collect_performance_data("vid_001", elapsed_hours=999999)
        assert result_large["elapsed_hours"] == 999999

    @pytest.mark.asyncio
    async def test_invalid_elapsed_hours_nan_inf_bool(self):
        """elapsed_hours に NaN, Infinity, bool が指定された場合に例外が発生すること"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        import math

        # NaN の場合
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=float("nan"))
        assert "cannot be NaN" in str(excinfo.value)

        # Infinity の場合
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=float("inf"))
        assert "cannot be Infinity" in str(excinfo.value)

        # bool (True) の場合
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=True)
        assert "cannot be a boolean" in str(excinfo.value)

        # bool (False) の場合
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=False)
        assert "cannot be a boolean" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_invalid_api_mode_raises_value_error(self):
        """不正な YOUTUBE_API_MODE が設定された場合に ValueError が発生すること"""
        collector = PostPublishCollector()
        
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "invalid_mode"}):
            with pytest.raises(PostPublishCollectorValueError) as excinfo:
                # 明示的な override がない限り、環境変数をチェックする
                _ = collector.api_mode
            assert "Invalid YOUTUBE_API_MODE" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_dynamic_api_mode_switching(self):
        """環境変数 YOUTUBE_API_MODE の変更が動的に反映されること"""
        collector = PostPublishCollector()
        
        # mock モード
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "mock"}):
            res = await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert res["is_mock"] is True

        # real モード
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "real"}):
            with pytest.raises(NotImplementedError):
                await collector.collect_performance_data("vid_001", elapsed_hours=24)

    @pytest.mark.asyncio
    async def test_drop_off_points_not_exceeding_duration(self):
        """ドロップオフポイントが平均視聴時間を超過しないこと"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        result = await collector.collect_performance_data("vid_001", elapsed_hours=24)
        avg_duration = result["metrics"]["average_view_duration_seconds"]
        
        for pt in result["retention_map"]["drop_off_points"]:
            min_str, sec_str = pt.split(":")
            pt_seconds = int(min_str) * 60 + int(sec_str)
            assert pt_seconds <= avg_duration

    @pytest.mark.asyncio
    async def test_empty_and_special_video_id(self):
        """空文字や特殊な文字を含む video_id に対する挙動"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        # 空文字 video_id は ValueError になる
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("", elapsed_hours=24)
        assert "cannot be empty" in str(excinfo.value)
        
        # 空白のみの video_id も ValueError になる
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("   ", elapsed_hours=24)
        assert "cannot be empty" in str(excinfo.value)

        # None の video_id は ValueError になる
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data(None, elapsed_hours=24)
        assert "cannot be None" in str(excinfo.value)

        # 文字列以外の video_id は TypeError になる
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            await collector.collect_performance_data(12345, elapsed_hours=24)
        assert "must be a string" in str(excinfo.value)
        
        # 特殊文字 video_id (正常値)
        special_id = "vid_!@#$%^&*()_+{}|:<>?-=[]\\;',./"
        result_special = await collector.collect_performance_data(special_id, elapsed_hours=24)
        assert result_special["video_id"] == special_id

    @pytest.mark.asyncio
    async def test_invalid_elapsed_hours_types(self):
        """elapsed_hours に無効な型を渡した際の挙動"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"

        # None の場合はデフォルト値 (24h) になる
        result_none = await collector.collect_performance_data("vid_001", elapsed_hours=None)
        assert result_none["elapsed_hours"] == 24
        assert result_none["metrics_timestamp"] == "2026-01-02T00:00:00"

        # 数値以外 (str) の場合は TypeError になる
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours="24")
        assert "must be a number" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_deterministic_seed_across_processes(self):
        """プロセスをまたいでも再現可能なハッシュシードの生成を検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        # 決定論的ハッシュ値の検証 (zlib.adler32)
        expected_seed = 312017657  # adler32 of "vid_001_24"
        assert collector._generate_seed("vid_001", 24) == expected_seed
        
        result = await collector.collect_performance_data("vid_001", elapsed_hours=24)
        
        # 決定論的に生成される具体的なモックデータの検証
        assert result["metrics"]["views"] == 34772
        assert result["metrics"]["click_through_rate"] == 8.4
        assert result["metrics"]["retention_rate_pct"] == 37.8

    @pytest.mark.asyncio
    async def test_deterministic_timestamp(self):
        """タイムスタンプが経過時間に応じて完全に決定論的であることを検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"

        result1 = await collector.collect_performance_data("vid_001", elapsed_hours=24)
        result2 = await collector.collect_performance_data("vid_001", elapsed_hours=24)

        # 何回呼び出しても同一のタイムスタンプが返ることを確認
        assert result1["metrics_timestamp"] == result2["metrics_timestamp"]
        # 基準日時 2026-01-01T00:00:00 + 24時間 = 2026-01-02T00:00:00 であることを確認
        assert result1["metrics_timestamp"] == "2026-01-02T00:00:00"

    @pytest.mark.asyncio
    async def test_zero_division_guard(self):
        """base_ctr が 0 の場合でも impressions 計算でゼロ除算が発生せず 0 になることを検証"""
        collector = PostPublishCollector()
        
        # _build_metrics を直接テストして base_ctr = 0.0 の挙動を確認
        metrics = collector._build_metrics(base_views=1000, base_ctr=0.0, base_retention=50.0)
        assert metrics["impressions"] == 0
        assert metrics["click_through_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_retention_max_cap(self):
        """維持率が 100% を超過しないようにガードされることを検証"""
        collector = PostPublishCollector()

        # base_retention = 90.0 の場合、通常なら +20% で 110% になるが、100% に丸められることを確認
        retention_map = collector._build_retention_map(base_retention=90.0)
        assert retention_map["0-30s"] == 100.0
        assert retention_map["30-60s"] == 100.0

    @pytest.mark.asyncio
    async def test_timedelta_overflow(self):
        """elapsed_hours に極端な値を指定した際に OverflowError / ValueError が発生し、base_time にフォールバックされることを検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        # timedelta が OverflowError もしくは ValueError を投げるような極端に大きな値を指定
        result = await collector.collect_performance_data("vid_001", elapsed_hours=10**18)
        
        # フォールバックにより base_time (2026-01-01T00:00:00) が設定されることを確認
        assert result["metrics_timestamp"] == "2026-01-01T00:00:00"
        assert result["elapsed_hours"] == 10**18

    @pytest.mark.asyncio
    async def test_custom_exceptions(self):
        """バリデーションエラー時にカスタム例外が発生することを検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"

        # video_id が None の場合
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data(None, elapsed_hours=24)
        assert "video_id cannot be None" in str(excinfo.value)

        # video_id が文字列以外の場合
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            await collector.collect_performance_data(12345, elapsed_hours=24)
        assert "video_id must be a string" in str(excinfo.value)

        # video_id が空文字の場合
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("", elapsed_hours=24)
        assert "video_id cannot be empty" in str(excinfo.value)

        # elapsed_hours が bool の場合
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=True)
        assert "cannot be a boolean" in str(excinfo.value)

        # elapsed_hours が無効な型（文字列）の場合
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours="24")
        assert "must be a number" in str(excinfo.value)

        # elapsed_hours が NaN の場合
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=float("nan"))
        assert "cannot be NaN" in str(excinfo.value)

        # elapsed_hours が Infinity の場合
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=float("inf"))
        assert "cannot be Infinity" in str(excinfo.value)

        # elapsed_hours が負数の場合
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=-24)
        assert "must be non-negative" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_float_elapsed_hours_handling(self):
        """float型のelapsed_hoursに対する処理を検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"

        # 小数値（端数あり）は ValueError
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=24.5)
        assert "must be a whole number" in str(excinfo.value)

        # 整数値（端数なし）は正常に処理され、intにキャストされる
        result = await collector.collect_performance_data("vid_001", elapsed_hours=24.0)
        assert isinstance(result["elapsed_hours"], int)
        assert result["elapsed_hours"] == 24
        
        # 決定論的データであることも確認
        expected_views = 34772
        assert result["metrics"]["views"] == expected_views

    @pytest.mark.asyncio
    async def test_timedelta_overflow_warning_logging(self, caplog):
        """timedelta overflow時に警告ログが出力されることを検証"""
        import logging
        collector = PostPublishCollector()
        collector.api_mode = "mock"

        with caplog.at_level(logging.WARNING):
            result = await collector.collect_performance_data("vid_001", elapsed_hours=10**18)
            
        assert result["metrics_timestamp"] == "2026-01-01T00:00:00"
        
        # ログメッセージの検証
        warnings = [record.message for record in caplog.records if record.levelname == "WARNING"]
        assert any("Failed to calculate mock time with elapsed_hours" in w for w in warnings)

    def test_api_mode_setter(self):
        """api_mode のセッターとゲッターが正しく動作し、バリデーションを行うこと"""
        collector = PostPublishCollector()
        
        # 初期状態は None
        assert collector._api_mode_override is None
        
        # セッターによる上書き
        collector.api_mode = "mock"
        assert collector.api_mode == "mock"
        
        collector.api_mode = "real"
        assert collector.api_mode == "real"
        
        # 不正な値のバリデーション
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            collector.api_mode = "invalid"
        assert "Invalid YOUTUBE_API_MODE" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_api_mode_override_precedence(self):
        """明示的な api_mode の設定が環境変数よりも優先されること"""
        collector = PostPublishCollector()
        
        # 環境変数が real だが、override が mock の場合
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "real"}):
            collector.api_mode = "mock"
            res = await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert res["is_mock"] is True
            
        # 環境変数が mock だが、override が real の場合
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "mock"}):
            collector.api_mode = "real"
            with pytest.raises(NotImplementedError):
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
    @pytest.mark.asyncio
    async def test_api_mode_case_insensitivity_env(self):
        """環境変数 YOUTUBE_API_MODE の大文字小文字の揺れが許容されること"""
        collector = PostPublishCollector()
        
        # 大文字混じりの "Mock"
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "Mock"}):
            assert collector.api_mode == "mock"
            res = await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert res["is_mock"] is True

        # 大文字の "REAL"
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "REAL"}):
            assert collector.api_mode == "real"
            with pytest.raises(NotImplementedError):
                await collector.collect_performance_data("vid_001", elapsed_hours=24)

    def test_api_mode_setter_none_reset(self):
        """api_mode のセッターに None を渡すことで上書き状態がクリアされ、環境変数の値が参照されるようになること"""
        collector = PostPublishCollector()
        
        # 1. 初期状態で環境変数を mock に設定
        with patch.dict(os.environ, {"YOUTUBE_API_MODE": "mock"}):
            assert collector.api_mode == "mock"
            
            # 2. real に上書き
            collector.api_mode = "real"
            assert collector.api_mode == "real"
            
            # 3. None をセットしてリセット
            collector.api_mode = None
            assert collector._api_mode_override is None
            # リセットされたので環境変数の mock が参照されるはず
            assert collector.api_mode == "mock"

    def test_api_mode_setter_case_insensitivity(self):
        """api_mode のセッターに大文字混じりの値を設定した場合でも正規化されて受け入れられること"""
        collector = PostPublishCollector()
        
        # "Mock" をセット
        collector.api_mode = "Mock"
        assert collector.api_mode == "mock"
        
        # "REAL" をセット
        collector.api_mode = "REAL"
        assert collector.api_mode == "real"

    def test_api_mode_env_none(self):
        """環境変数 YOUTUBE_API_MODE が未設定の場合、モジュールデフォルト値がゲッターで参照されること"""
        collector = PostPublishCollector()
        with patch.dict(os.environ, {}, clear=True):
            collector.api_mode = None
            # 環境変数になく override もない場合、モジュールのデフォルト値が参照される
            assert collector.api_mode in ("mock", "real")

    def test_api_mode_setter_invalid_type(self):
        """api_mode のセッターに文字列や None 以外の型を設定した際に TypeError が発生すること"""
        collector = PostPublishCollector()
        with pytest.raises(PostPublishCollectorTypeError) as excinfo:
            collector.api_mode = 12345
        assert "must be a string or None" in str(excinfo.value)

    def test_api_mode_getter_invalid_type(self):
        """グローバル変数や環境変数の api_mode が不正な型の場合に TypeError が発生すること"""
        collector = PostPublishCollector()
        
        # グローバル変数をパッチして不正な型にする
        with patch("services.post_publish_collector.YOUTUBE_API_MODE", 12345):
            with pytest.raises(PostPublishCollectorTypeError) as excinfo:
                _ = collector.api_mode
            assert "must be a string" in str(excinfo.value)

    def test_retention_min_cap(self):
        """維持率が 0.0% 未満に低下しないようにガードされることを検証"""
        collector = PostPublishCollector()
        # base_retention = -50.0 の場合、下限が 0.0 に丸められることを確認
        retention_map = collector._build_retention_map(base_retention=-50.0)
        assert retention_map["0-30s"] == 0.0
        assert retention_map["30-60s"] == 0.0

    def test_metrics_non_negative(self):
        """基本メトリクスに負の値が渡された場合でも、詳細メトリクスが非負（0以上）にガードされること"""
        collector = PostPublishCollector()
        # 負の値を渡して各メトリクスが 0 もしくは 0.0 以上になることを確認
        metrics = collector._build_metrics(base_views=-100, base_ctr=-5.0, base_retention=-20.0)
        assert metrics["views"] >= 0
        assert metrics["impressions"] >= 0
        assert metrics["click_through_rate"] >= 0.0
        assert metrics["average_view_duration_seconds"] >= 0
        assert metrics["retention_rate_pct"] >= 0.0
        assert metrics["likes"] >= 0
        assert metrics["comments"] >= 0

    @pytest.mark.asyncio
    async def test_union_type_acceptance_explicit(self):
        """elapsed_hours に float の 72.0 を渡して、正常に int(72) として処理されること"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        result = await collector.collect_performance_data("vid_001", elapsed_hours=72.0)
        assert isinstance(result["elapsed_hours"], int)
        assert result["elapsed_hours"] == 72

    def test_api_mode_env_invalid_type(self):
        """環境変数 YOUTUBE_API_MODE が文字列以外の型（モック経由）の場合に TypeError が発生すること"""
        collector = PostPublishCollector()
        with patch("os.environ.get", return_value=12345):
            with pytest.raises(PostPublishCollectorTypeError) as excinfo:
                _ = collector.api_mode
            assert "must be a string" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_real_mode_raises_custom_not_implemented(self):
        """real モードでは PostPublishCollectorNotImplementedError が発生すること"""
        collector = PostPublishCollector()
        collector.api_mode = "real"
        
        with pytest.raises(PostPublishCollectorNotImplementedError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=24)
        
        # 厳密な型チェックとインスタンスチェック
        assert type(excinfo.value) is PostPublishCollectorNotImplementedError
        assert isinstance(excinfo.value, NotImplementedError)
        assert isinstance(excinfo.value, PostPublishCollectorValueError) is False  # サブクラスではない
        assert "YouTube Analytics API の本番統合は未実装です" in str(excinfo.value)

    def test_internal_build_metrics_validation(self):
        """_build_metrics の不正な引数に対するバリデーションを検証"""
        collector = PostPublishCollector()
        
        # base_views のバリデーション
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=None, base_ctr=5.0, base_retention=50.0)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_metrics(base_views=True, base_ctr=5.0, base_retention=50.0)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_metrics(base_views="1000", base_ctr=5.0, base_retention=50.0)
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=float("nan"), base_ctr=5.0, base_retention=50.0)
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=float("inf"), base_ctr=5.0, base_retention=50.0)
            
        # base_ctr のバリデーション
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=1000, base_ctr=None, base_retention=50.0)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_metrics(base_views=1000, base_ctr=False, base_retention=50.0)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_metrics(base_views=1000, base_ctr="5.0", base_retention=50.0)
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=1000, base_ctr=float("nan"), base_retention=50.0)
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=1000, base_ctr=float("inf"), base_retention=50.0)
            
        # base_retention のバリデーション
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=1000, base_ctr=5.0, base_retention=None)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_metrics(base_views=1000, base_ctr=5.0, base_retention=False)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_metrics(base_views=1000, base_ctr=5.0, base_retention="50.0")
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=1000, base_ctr=5.0, base_retention=float("nan"))
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_metrics(base_views=1000, base_ctr=5.0, base_retention=float("inf"))

    def test_internal_build_retention_map_validation(self):
        """_build_retention_map の不正な引数に対するバリデーションを検証"""
        collector = PostPublishCollector()
        
        # base_retention のバリデーション
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_retention_map(base_retention=None, max_duration_seconds=600)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_retention_map(base_retention=True, max_duration_seconds=600)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_retention_map(base_retention="50.0", max_duration_seconds=600)
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_retention_map(base_retention=float("nan"), max_duration_seconds=600)
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_retention_map(base_retention=float("inf"), max_duration_seconds=600)
            
        # max_duration_seconds のバリデーション
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_retention_map(base_retention=50.0, max_duration_seconds=None)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_retention_map(base_retention=50.0, max_duration_seconds=True)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._build_retention_map(base_retention=50.0, max_duration_seconds="600")
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_retention_map(base_retention=50.0, max_duration_seconds=float("nan"))
        with pytest.raises(PostPublishCollectorValueError):
            collector._build_retention_map(base_retention=50.0, max_duration_seconds=float("inf"))

    def test_internal_generate_seed_validation(self):
        """_generate_seed の不正な引数に対するバリデーションを検証"""
        collector = PostPublishCollector()
        
        # video_id のバリデーション
        with pytest.raises(PostPublishCollectorValueError):
            collector._generate_seed(video_id=None, elapsed_hours=24)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._generate_seed(video_id=123, elapsed_hours=24)
            
        # elapsed_hours のバリデーション
        with pytest.raises(PostPublishCollectorValueError):
            collector._generate_seed(video_id="vid_001", elapsed_hours=None)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._generate_seed(video_id="vid_001", elapsed_hours=False)
        with pytest.raises(PostPublishCollectorTypeError):
            collector._generate_seed(video_id="vid_001", elapsed_hours="24")

    def test_impressions_overflow_guard_comprehensive(self):
        """ctr が極めて小さい場合、または計算上オーバーフローを引き起こす値の場合に安全に impressions が 0 になることを検証"""
        collector = PostPublishCollector()
        
        # 1. CTRが極小（1e-300）の場合
        metrics = collector._build_metrics(base_views=50000, base_ctr=1e-300, base_retention=50.0)
        assert metrics["impressions"] == 0

        # 2. CTRがアンダーフローして 0 になり ZeroDivisionError を引き起こしうる場合 (1e-325)
        metrics = collector._build_metrics(base_views=50000, base_ctr=1e-325, base_retention=50.0)
        assert metrics["impressions"] == 0

        # 3. float演算の結果がinfになり int(inf) で OverflowError を引き起こす場合 (views=10**315, ctr=0.01)
        metrics = collector._build_metrics(base_views=10**315, base_ctr=0.01, base_retention=50.0)
        assert metrics["impressions"] == 0

    def test_generate_seed_zlib_error_fallback(self):
        """zlib で例外が発生した場合に安全に決定論的なシード値へフォールバックされることの検証"""
        collector = PostPublishCollector()
        
        import zlib
        # services.post_publish_collector 内の zlib.adler32 をモック化
        with patch("services.post_publish_collector.zlib.adler32", side_effect=zlib.error("Mocked zlib error")):
            seed = collector._generate_seed("vid_001", 24)
            # Polynomial rolling hashによる決定論的ハッシュ値 ("vid_001_24") をアサート
            expected_hash = 0
            for char in "vid_001_24":
                expected_hash = (31 * expected_hash + ord(char)) % (2**32)
            assert seed == expected_hash

            # 再現性（決定論的）であることを確認
            seed2 = collector._generate_seed("vid_001", 24)
            assert seed == seed2

    def test_build_retention_map_parse_error_fallback(self):
        """ALL_POINTS に不正な形式の値が含まれていても、例外を発生させずにスキップされること"""
        collector = PostPublishCollector()
        
        # ALL_POINTS に不正な値をパッチ
        with patch("services.post_publish_collector.ALL_POINTS", ["invalid_format", None, 1234, "01:24"]):
            result = collector._build_retention_map(base_retention=50.0, max_duration_seconds=600)
            # 正常にパースできた "01:24" (84秒 <= 600秒) のみ filtered_points (drop_off_points) に入る
            assert "01:24" in result["drop_off_points"]
            assert len(result["drop_off_points"]) == 1

    @pytest.mark.asyncio
    async def test_collect_performance_data_exception_wrapping(self):
        """内部処理で ValueError や TypeError などの例外が発生した際に、それぞれ対応するカスタム例外に適切にラッピングされること、および予期しない例外（KeyError等）は生のまま透過されること"""
        collector = PostPublishCollector()
        
        # 1. ValueError が PostPublishCollectorValueError にラッピングされること
        with patch.object(collector, "_generate_mock_data", side_effect=ValueError("Mocked value error")):
            with pytest.raises(PostPublishCollectorValueError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Failed to collect performance data" in str(excinfo.value)
            assert isinstance(excinfo.value.__cause__, ValueError)

        # 2. TypeError が PostPublishCollectorTypeError にラッピングされること
        with patch.object(collector, "_generate_mock_data", side_effect=TypeError("Mocked type error")):
            with pytest.raises(PostPublishCollectorTypeError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Failed to collect performance data" in str(excinfo.value)
            assert isinstance(excinfo.value.__cause__, TypeError)

        # 3. 内部で既に PostPublishCollectorError が発生した場合はラッピングせず透過的に再送出すること
        with patch.object(collector, "_generate_mock_data", side_effect=PostPublishCollectorValueError("Mocked custom error")):
            with pytest.raises(PostPublishCollectorValueError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Mocked custom error" in str(excinfo.value)

        # 4. 予期しないプログラミング例外（KeyError等）は PostPublishCollectorError にラッピングされること
        with patch.object(collector, "_generate_mock_data", side_effect=KeyError("Mocked key error")):
            with pytest.raises(PostPublishCollectorError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Unexpected error during performance data collection" in str(excinfo.value)
            assert isinstance(excinfo.value.__cause__, KeyError)


        # 5. OSError が PostPublishCollectorNetworkError にラッピングされること
        with patch.object(collector, "_generate_mock_data", side_effect=OSError("Mocked OS error")):
            with pytest.raises(PostPublishCollectorNetworkError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Network or I/O failure" in str(excinfo.value)
            assert isinstance(excinfo.value.__cause__, OSError)

        # 6. asyncio.TimeoutError が PostPublishCollectorNetworkError にラッピングされること
        with patch.object(collector, "_generate_mock_data", side_effect=asyncio.TimeoutError("Mocked timeout error")):
            with pytest.raises(PostPublishCollectorNetworkError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Network or I/O failure" in str(excinfo.value)
            assert isinstance(excinfo.value.__cause__, asyncio.TimeoutError)

        # 7. OverflowError が PostPublishCollectorError にラッピングされること
        with patch.object(collector, "_generate_mock_data", side_effect=OverflowError("Mocked overflow error")):
            with pytest.raises(PostPublishCollectorError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Overflow during performance data collection" in str(excinfo.value)
            assert isinstance(excinfo.value.__cause__, OverflowError)

    @pytest.mark.asyncio
    async def test_collect_performance_data_logging_on_value_error(self, caplog):
        """ValueError が発生した際に、logger.error で適切にログが出力されることを検証"""
        import logging
        collector = PostPublishCollector()
        
        with patch.object(collector, "_generate_mock_data", side_effect=ValueError("Mocked value error")):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(PostPublishCollectorValueError):
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
            
            # ERROR レベルのログが出力されていることを確認
            errors = [record.message for record in caplog.records if record.levelname == "ERROR"]
            assert any("Validation value error while collecting performance data" in msg for msg in errors)

    @pytest.mark.asyncio
    async def test_collect_performance_data_logging_on_type_error(self, caplog):
        """TypeError が発生した際に、logger.error で適切にログが出力されることを検証"""
        import logging
        collector = PostPublishCollector()
        
        with patch.object(collector, "_generate_mock_data", side_effect=TypeError("Mocked type error")):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(PostPublishCollectorTypeError):
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
            
            # ERROR レベルのログが出力されていることを確認
            errors = [record.message for record in caplog.records if record.levelname == "ERROR"]
            assert any("Validation type error while collecting performance data" in msg for msg in errors)

    @pytest.mark.asyncio
    async def test_collect_performance_data_logging_on_network_error(self, caplog):
        """ネットワークやI/Oエラーが発生した際に、logger.error でスタックトレースがログ出力されることを検証"""
        import logging
        collector = PostPublishCollector()
        
        with patch.object(collector, "_generate_mock_data", side_effect=OSError("Mocked OS error")):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(PostPublishCollectorNetworkError):
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
            
            # ERROR レベルのログが出力されていることを確認
            errors = [record.message for record in caplog.records if record.levelname == "ERROR"]
            assert any("Network or I/O error while collecting performance data" in msg for msg in errors)

    @pytest.mark.asyncio
    async def test_collect_performance_data_logging_on_unexpected_error(self, caplog):
        """予期せぬ例外が発生した際に、logger.error でスタックトレースがログ出力されることを検証"""
        import logging
        collector = PostPublishCollector()
        
        with patch.object(collector, "_generate_mock_data", side_effect=KeyError("Mocked key error")):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(PostPublishCollectorError):
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
            
            # ERROR レベルのログが出力されていることを確認
            errors = [record.message for record in caplog.records if record.levelname == "ERROR"]
            assert any("Unexpected error while collecting performance data" in msg for msg in errors)

    @pytest.mark.asyncio
    async def test_elapsed_hours_extreme_floating_point(self):

        """極小の端数を持つ float 型の elapsed_hours が与えられた場合に ValueError が発生すること"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"

        # わずかな端数がある場合、whole numberではないため ValueError
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data("vid_001", elapsed_hours=24.0000000001)
        assert "must be a whole number" in str(excinfo.value)

    def test_generate_seed_float_equivalence(self):
        """float型の24.0とint型の24で、同じハッシュシードが生成されることを検証"""
        collector = PostPublishCollector()
        seed_int = collector._generate_seed("vid_001", 24)
        seed_float = collector._generate_seed("vid_001", 24.0)
        assert seed_int == seed_float

    def test_generate_seed_zlib_error_warning_logged(self, caplog):
        """zlibエラー発生時に警告ログが出力されることを検証"""
        import logging
        import zlib
        collector = PostPublishCollector()
        with patch("services.post_publish_collector.zlib.adler32", side_effect=zlib.error("Mocked zlib error")):
            with caplog.at_level(logging.WARNING):
                collector._generate_seed("vid_001", 24)
            warnings = [record.message for record in caplog.records if record.levelname == "WARNING"]
            assert any("zlib adler32 seed generation failed" in w for w in warnings)

    def test_build_retention_map_parse_error_warning_logged(self, caplog):
        """リテンションマップ構築時にパースエラーが発生した場合に警告ログが出力されることを検証"""
        import logging
        collector = PostPublishCollector()
        with patch("services.post_publish_collector.ALL_POINTS", ["invalid_format"]):
            with caplog.at_level(logging.WARNING):
                collector._build_retention_map(base_retention=50.0, max_duration_seconds=600)
            warnings = [record.message for record in caplog.records if record.levelname == "WARNING"]
            assert any("Skipping invalid retention point format" in w for w in warnings)

    def test_custom_exceptions_exist(self):
        """新規追加したカスタム例外クラスが正しくインポートされ、PostPublishCollectorErrorを継承していることを検証"""
        assert issubclass(PostPublishCollectorAPIError, PostPublishCollectorError)
        assert issubclass(PostPublishCollectorNetworkError, PostPublishCollectorError)

    @pytest.mark.asyncio
    async def test_video_id_length_validation(self):
        """video_id が128文字を超える場合に PostPublishCollectorValueError が発生することを検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        long_id = "a" * 129
        with pytest.raises(PostPublishCollectorValueError) as excinfo:
            await collector.collect_performance_data(long_id, elapsed_hours=24)
        assert "video_id cannot exceed 128 characters" in str(excinfo.value)

        # ちょうど 128 文字は通ること
        border_id = "a" * 128
        result = await collector.collect_performance_data(border_id, elapsed_hours=24)
        assert result["video_id"] == border_id

    @pytest.mark.asyncio
    async def test_collect_performance_data_http_error_wrapping(self):
        """googleapiclient の HttpError (ダミー) が発生したときに、PostPublishCollectorAPIError にマッピングされることを検証"""
        collector = PostPublishCollector()
        
        class DummyHttpError(Exception):
            pass

        # services.post_publish_collector.HttpError を DummyHttpError にパッチ
        with patch("services.post_publish_collector.HttpError", DummyHttpError):
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpError("Mocked HTTP API error")):
                with pytest.raises(PostPublishCollectorAPIError) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "YouTube API returned HTTP error" in str(excinfo.value)
                assert isinstance(excinfo.value.__cause__, DummyHttpError)

    def test_generate_seed_expanded_exceptions_fallback(self):
        """_generate_seed において TypeError や ValueError が発生した際、安全にフォールバックすることの検証"""
        collector = PostPublishCollector()
        
        # 1. zlib.adler32 で TypeError が発生した場合
        with patch("services.post_publish_collector.zlib.adler32", side_effect=TypeError("Mocked type error")):
            seed = collector._generate_seed("vid_001", 24)
            expected_hash = 0
            for char in "vid_001_24":
                expected_hash = (31 * expected_hash + ord(char)) % (2**32)
            assert seed == expected_hash

        # 2. zlib.adler32 で ValueError が発生した場合
        with patch("services.post_publish_collector.zlib.adler32", side_effect=ValueError("Mocked value error")):
            seed = collector._generate_seed("vid_001", 24)
            expected_hash = 0
            for char in "vid_001_24":
                expected_hash = (31 * expected_hash + ord(char)) % (2**32)
            assert seed == expected_hash

        # 3. zlib.adler32 で AttributeError が発生した場合
        with patch("services.post_publish_collector.zlib.adler32", side_effect=AttributeError("Mocked attribute error")):
            seed = collector._generate_seed("vid_001", 24)
            expected_hash = 0
            for char in "vid_001_24":
                expected_hash = (31 * expected_hash + ord(char)) % (2**32)
            assert seed == expected_hash

    def test_http_error_import_missing(self):
        """googleapiclient がインポートできない場合に HttpError がダミーの例外クラスになることを検証"""
        import sys
        import importlib
        import builtins
        
        modules_backup = {}
        for key in list(sys.modules.keys()):
            if key == "googleapiclient" or key.startswith("googleapiclient."):
                modules_backup[key] = sys.modules.pop(key)
        
        original_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if "googleapiclient" in name:
                raise ImportError("Mocked import failure")
            return original_import(name, *args, **kwargs)
            
        with patch("builtins.__import__", side_effect=mock_import):
            import services.post_publish_collector
            importlib.reload(services.post_publish_collector)
            assert issubclass(services.post_publish_collector.HttpError, Exception)
            assert services.post_publish_collector.HttpError.__name__ == "HttpError"
            
        for key, val in modules_backup.items():
            sys.modules[key] = val
        importlib.reload(services.post_publish_collector)

    def test_http_error_import_present(self):
        """googleapiclient がインポートできる場合に HttpError が正しく設定されることを検証"""
        import sys
        import importlib
        from types import ModuleType
        
        modules_backup = {}
        for key in list(sys.modules.keys()):
            if key == "googleapiclient" or key.startswith("googleapiclient."):
                modules_backup[key] = sys.modules.pop(key)

        mock_errors = ModuleType("errors")
        class DummyHttpError(Exception):
            pass
        mock_errors.HttpError = DummyHttpError
        
        mock_googleapiclient = ModuleType("googleapiclient")
        mock_googleapiclient.errors = mock_errors
        
        sys.modules["googleapiclient"] = mock_googleapiclient
        sys.modules["googleapiclient.errors"] = mock_errors
        
        try:
            import services.post_publish_collector
            importlib.reload(services.post_publish_collector)
            assert services.post_publish_collector.HttpError is DummyHttpError
        finally:
            if "googleapiclient" in sys.modules:
                del sys.modules["googleapiclient"]
            if "googleapiclient.errors" in sys.modules:
                del sys.modules["googleapiclient.errors"]
            
            for key, val in modules_backup.items():
                sys.modules[key] = val
            importlib.reload(services.post_publish_collector)

    @pytest.mark.asyncio
    async def test_collect_performance_data_http_error_detailed_wrapping(self):
        """HTTPエラー発生時に、ステータスコードに応じて適切なカスタム例外が発生することを検証"""
        collector = PostPublishCollector()
        
        # モジュールから動的に最新の例外クラスを取得（reload対策）
        import services.post_publish_collector
        err_auth = services.post_publish_collector.PostPublishCollectorAuthError
        err_quota = services.post_publish_collector.PostPublishCollectorQuotaError
        err_notfound = services.post_publish_collector.PostPublishCollectorNotFoundError
        err_api = services.post_publish_collector.PostPublishCollectorAPIError
        
        class DummyResp:
            def __init__(self, status):
                self.status = status

        class DummyHttpErrorWithStatus(Exception):
            def __init__(self, status, content="Error message"):
                self.resp = DummyResp(status)
                self.content = content
                super().__init__(content)

        # services.post_publish_collector.HttpError を DummyHttpErrorWithStatus にパッチ
        with patch("services.post_publish_collector.HttpError", DummyHttpErrorWithStatus):
            # 1. 401 Unauthorized の場合 -> PostPublishCollectorAuthError
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpErrorWithStatus(401, "Unauthorized")):
                with pytest.raises(err_auth) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "authentication or permission failed" in str(excinfo.value)
                assert excinfo.value.__cause__.resp.status == 401

            # 2. 403 Forbidden (クォータ超過ではない) の場合 -> PostPublishCollectorAuthError
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpErrorWithStatus(403, "Access denied")):
                with pytest.raises(err_auth) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "authentication or permission failed" in str(excinfo.value)
                assert excinfo.value.__cause__.resp.status == 403

            # 3. 403 Forbidden (クォータ超過) の場合 -> PostPublishCollectorQuotaError
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpErrorWithStatus(403, "Quota exceeded for limits")):
                with pytest.raises(err_quota) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "quota exceeded or limit reached" in str(excinfo.value)
                assert excinfo.value.__cause__.resp.status == 403

            # 4. 404 Not Found の場合 -> PostPublishCollectorNotFoundError
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpErrorWithStatus(404, "Not Found")):
                with pytest.raises(err_notfound) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "video or resource not found" in str(excinfo.value)
                assert excinfo.value.__cause__.resp.status == 404

            # 5. 500 Internal Server Error の場合 -> PostPublishCollectorAPIError
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpErrorWithStatus(500, "Internal Server Error")):
                with pytest.raises(err_api) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "YouTube API returned HTTP error" in str(excinfo.value)
                assert excinfo.value.__cause__.resp.status == 500

    def test_new_custom_exceptions_inherit_base(self):
        """新しいカスタム例外クラスが正しく PostPublishCollectorError を継承していることを検証"""
        import services.post_publish_collector
        err_auth = services.post_publish_collector.PostPublishCollectorAuthError
        err_quota = services.post_publish_collector.PostPublishCollectorQuotaError
        err_notfound = services.post_publish_collector.PostPublishCollectorNotFoundError
        err_base = services.post_publish_collector.PostPublishCollectorError
        assert issubclass(err_auth, err_base)
        assert issubclass(err_quota, err_base)
        assert issubclass(err_notfound, err_base)

    @pytest.mark.asyncio
    async def test_elapsed_hours_huge_int_no_overflow(self):
        """極めて大きな整数の elapsed_hours が与えられた場合に OverflowError が発生せず、安全に timedelta 境界警告が発生することを検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        result = await collector.collect_performance_data("vid_001", elapsed_hours=10**300)
        assert result["elapsed_hours"] == 10**300
        assert result["metrics_timestamp"] == "2026-01-01T00:00:00"

    @pytest.mark.asyncio
    async def test_collect_performance_data_http_error_string_status_code(self):
        """HTTPエラー発生時に、ステータスコードが文字列であっても正しく数値パースされて適切なカスタム例外が発生することを検証"""
        collector = PostPublishCollector()
        
        import services.post_publish_collector
        err_auth = services.post_publish_collector.PostPublishCollectorAuthError
        err_api = services.post_publish_collector.PostPublishCollectorAPIError
        
        class DummyResp:
            def __init__(self, status):
                self.status = status

        class DummyHttpErrorWithStatus(Exception):
            def __init__(self, status, content="Error message"):
                self.resp = DummyResp(status)
                self.content = content
                super().__init__(content)

        with patch("services.post_publish_collector.HttpError", DummyHttpErrorWithStatus):
            # "401" の場合 -> PostPublishCollectorAuthError
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpErrorWithStatus("401", "Unauthorized")):
                with pytest.raises(err_auth) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "authentication or permission failed" in str(excinfo.value)

            # パース不可能な文字列の場合（"invalid_code"） -> PostPublishCollectorAPIError
            with patch.object(collector, "_generate_mock_data", side_effect=DummyHttpErrorWithStatus("invalid_code", "Bad Gateway")):
                with pytest.raises(err_api) as excinfo:
                    await collector.collect_performance_data("vid_001", elapsed_hours=24)
                assert "YouTube API returned HTTP error" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_collect_performance_data_program_errors_propagated(self):
        """プログラムエラー（AttributeError など）が発生した際に、PostPublishCollectorError にラップされずにそのまま透過して投げられることを検証"""
        collector = PostPublishCollector()
        collector.api_mode = "mock"
        
        # AttributeError を発生させる
        with patch.object(collector, "_generate_mock_data", side_effect=AttributeError("Simulated attribute error")):
            with pytest.raises(AttributeError) as excinfo:
                await collector.collect_performance_data("vid_001", elapsed_hours=24)
            assert "Simulated attribute error" in str(excinfo.value)
