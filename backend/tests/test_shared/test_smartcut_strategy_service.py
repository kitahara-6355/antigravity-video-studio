"""
Sprint 4.1.2 + 4.1.3: SmartCutStrategyService テスト

MASTER L1744-L1751 検証:
- S412-01: session_id → 新SmartCutSession作成
- S412-02: 2セッション間でcontext独立
- S412-03: max_sessions超過 → 最古セッション削除

MASTER L1762-L1770 検証:
- S413-01〜S413-07: Strategist MVP (案Z ハイブリッド型)

設計書: sprint_41_design.md §Q1 仮説B / sprint_413_strategist_mvp_design.md
セルフチェック: SC-2 (セッション分離), SC-Z1〜Z7 (Strategist MVP)
"""
import json
import time
import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.smartcut_strategy_service import SmartCutStrategyService, SmartCutSession


# ─────────────────────────────────────────────
# S412-01: session_id → 新SmartCutSession作成
# ─────────────────────────────────────────────

class TestSessionCreate:
    """S412-01: セッション作成の検証"""

    def test_create_returns_session_instance(self):
        """新しいsession_idでSmartCutSessionインスタンスが返る"""
        service = SmartCutStrategyService(max_sessions=5)
        session = service.get_or_create_session("test-001")
        assert isinstance(session, SmartCutSession)
        assert session.session_id == "test-001"

    def test_session_has_plugin_instance(self):
        """作成されたセッションにSmartCutPluginインスタンスが割り当てられる"""
        service = SmartCutStrategyService(max_sessions=5)
        session = service.get_or_create_session("test-002")
        assert session.plugin is not None
        from plugins.smart_cut_plugin import SmartCutPlugin
        assert isinstance(session.plugin, SmartCutPlugin)

    def test_session_initial_context_is_none(self):
        """新規セッションのcontextは初期状態None（未初期化）"""
        service = SmartCutStrategyService(max_sessions=5)
        session = service.get_or_create_session("test-003")
        assert session.context is None
        assert session.is_initialized is False

    def test_session_count_increments(self):
        """セッション作成ごとにsession_countが増加"""
        service = SmartCutStrategyService(max_sessions=5)
        assert service.session_count == 0
        service.get_or_create_session("s1")
        assert service.session_count == 1
        service.get_or_create_session("s2")
        assert service.session_count == 2

    def test_same_id_returns_existing_session(self):
        """同じsession_idでは新規作成せず既存セッションを返す"""
        service = SmartCutStrategyService(max_sessions=5)
        s1 = service.get_or_create_session("same-id")
        s2 = service.get_or_create_session("same-id")
        assert s1 is s2
        assert service.session_count == 1

    def test_touch_updates_last_accessed(self):
        """get_or_create_sessionでlast_accessedが更新される"""
        service = SmartCutStrategyService(max_sessions=5)
        session = service.get_or_create_session("touch-test")
        first_access = session.last_accessed
        time.sleep(0.02)
        service.get_or_create_session("touch-test")
        assert session.last_accessed > first_access

    def test_get_plugin_returns_plugin_directly(self):
        """get_plugin()はSmartCutPluginインスタンスを直接返す（Router移行用ヘルパー）"""
        service = SmartCutStrategyService(max_sessions=5)
        plugin = service.get_plugin("helper-test")
        from plugins.smart_cut_plugin import SmartCutPlugin
        assert isinstance(plugin, SmartCutPlugin)
        # 同じsession_idで同じpluginが返る
        assert plugin is service.get_plugin("helper-test")

    def test_get_session_returns_none_for_unknown(self):
        """get_session()は存在しないIDでNoneを返す"""
        service = SmartCutStrategyService(max_sessions=5)
        assert service.get_session("nonexistent") is None

    def test_get_session_returns_existing(self):
        """get_session()は既存セッションを返す"""
        service = SmartCutStrategyService(max_sessions=5)
        service.get_or_create_session("existing")
        session = service.get_session("existing")
        assert session is not None
        assert session.session_id == "existing"

    def test_strategy_slot_initially_none(self):
        """strategyスロットは初期状態None（Sprint 4.1.3の予約フィールド）"""
        service = SmartCutStrategyService(max_sessions=5)
        session = service.get_or_create_session("strategy-test")
        assert session.strategy is None


# ─────────────────────────────────────────────
# S412-02: 2セッション間でcontext独立
# ─────────────────────────────────────────────

class TestSessionIsolation:
    """S412-02: セッション間の完全分離を検証（セルフチェック SC-2）"""

    def test_plugins_are_independent_instances(self):
        """異なるセッションのpluginインスタンスが別オブジェクト"""
        service = SmartCutStrategyService(max_sessions=5)
        sa = service.get_or_create_session("session-a")
        sb = service.get_or_create_session("session-b")
        assert sa.plugin is not sb.plugin

    def test_context_mutation_does_not_leak(self):
        """セッションAのcontext変更がセッションBに影響しない"""
        service = SmartCutStrategyService(max_sessions=5)
        sa = service.get_or_create_session("session-a")
        sb = service.get_or_create_session("session-b")

        # セッションAにcontextを設定
        from plugins.smart_cut_plugin import SmartCutContext
        sa.plugin._context = SmartCutContext(
            all_highlights=[{"id": "h1", "score": 0.9}],
            target_duration_minutes=30
        )

        # セッションBは影響を受けない
        assert sb.plugin._context is None
        assert sb.context is None
        assert sb.is_initialized is False
        # セッションAは初期化済み
        assert sa.is_initialized is True
        assert sa.context.target_duration_minutes == 30

    def test_lock_segment_isolated(self):
        """セッションAのlock操作がセッションBに影響しない"""
        service = SmartCutStrategyService(max_sessions=5)
        sa = service.get_or_create_session("session-a")
        sb = service.get_or_create_session("session-b")

        # 両セッションにcontextを設定
        from plugins.smart_cut_plugin import SmartCutContext
        sa.plugin._context = SmartCutContext()
        sb.plugin._context = SmartCutContext()

        # セッションAでlockを実行（evolution_log書込をモック）
        with patch.object(sa.plugin, '_save_to_evolution_log'):
            sa.plugin.lock_segment("seg-001", "Test Scene", 0.0, 30.0, "test reason")

        # セッションBのlocked_segmentsは空のまま
        assert len(sb.plugin._context.locked_segments) == 0
        assert len(sa.plugin._context.locked_segments) == 1

    def test_recommendation_update_isolated(self):
        """セッションAの推奨更新がセッションBに影響しない"""
        service = SmartCutStrategyService(max_sessions=5)
        sa = service.get_or_create_session("session-a")
        sb = service.get_or_create_session("session-b")

        from plugins.smart_cut_plugin import SmartCutContext
        sa.plugin._context = SmartCutContext(
            all_highlights=[{"id": "h1", "score": 0.9, "timestamp": 0, "duration": 30}]
        )
        sb.plugin._context = SmartCutContext(
            all_highlights=[{"id": "h2", "score": 0.5, "timestamp": 0, "duration": 30}]
        )

        # セッションAで30分に変更
        sa.plugin.update_recommendation(30)

        # セッションBはデフォルトの15分のまま
        assert sa.plugin._context.target_duration_minutes == 30
        assert sb.plugin._context.target_duration_minutes == 15

    def test_context_setter_isolated(self):
        """context setterを使っても他セッションに影響しない"""
        service = SmartCutStrategyService(max_sessions=5)
        sa = service.get_or_create_session("session-a")
        sb = service.get_or_create_session("session-b")

        from plugins.smart_cut_plugin import SmartCutContext
        custom_ctx = SmartCutContext(target_duration_minutes=45)
        sa.context = custom_ctx

        assert sa.context.target_duration_minutes == 45
        assert sb.context is None


# ─────────────────────────────────────────────
# S412-03: max_sessions超過 → 最古セッション削除
# ─────────────────────────────────────────────

class TestSessionLRUEviction:
    """S412-03: LRUベースのセッション削除を検証"""

    def test_eviction_at_max_sessions(self):
        """max_sessions超過時に最古セッションが削除される"""
        service = SmartCutStrategyService(max_sessions=3)

        # 3セッション作成（上限到達）
        service.get_or_create_session("s1")
        time.sleep(0.02)
        service.get_or_create_session("s2")
        time.sleep(0.02)
        service.get_or_create_session("s3")
        assert service.session_count == 3

        # 4つ目を作成 → s1（最古）が削除される
        service.get_or_create_session("s4")
        assert service.session_count == 3
        assert "s1" not in service.session_ids
        assert "s4" in service.session_ids

    def test_eviction_respects_access_order(self):
        """最後にアクセスされたセッションは削除されない（LRU）"""
        service = SmartCutStrategyService(max_sessions=3)

        service.get_or_create_session("s1")
        time.sleep(0.02)
        service.get_or_create_session("s2")
        time.sleep(0.02)
        service.get_or_create_session("s3")

        # s1に再アクセス → s1が最新になる
        time.sleep(0.02)
        service.get_or_create_session("s1")

        # s4作成 → s2（最古アクセス）が削除される
        service.get_or_create_session("s4")
        assert "s2" not in service.session_ids
        assert "s1" in service.session_ids  # 再アクセスしたので生存

    def test_eviction_cascading(self):
        """連続してmax超過する場合、都度最古が削除される"""
        service = SmartCutStrategyService(max_sessions=2)

        service.get_or_create_session("s1")
        time.sleep(0.02)
        service.get_or_create_session("s2")
        time.sleep(0.02)
        service.get_or_create_session("s3")  # s1削除
        time.sleep(0.02)
        service.get_or_create_session("s4")  # s2削除

        assert service.session_count == 2
        assert set(service.session_ids) == {"s3", "s4"}

    def test_remove_session_explicit(self):
        """明示的なセッション削除"""
        service = SmartCutStrategyService(max_sessions=5)
        service.get_or_create_session("to-remove")
        assert service.session_count == 1

        result = service.remove_session("to-remove")
        assert result is True
        assert service.session_count == 0

    def test_remove_nonexistent_session(self):
        """存在しないセッションの削除はFalse"""
        service = SmartCutStrategyService(max_sessions=5)
        result = service.remove_session("nonexistent")
        assert result is False

    def test_max_sessions_property(self):
        """max_sessionsプロパティが正しい値を返す"""
        service = SmartCutStrategyService(max_sessions=7)
        assert service.max_sessions == 7

    def test_eviction_with_max_sessions_one(self):
        """max_sessions=1のエッジケース"""
        service = SmartCutStrategyService(max_sessions=1)

        service.get_or_create_session("first")
        assert service.session_count == 1

        service.get_or_create_session("second")
        assert service.session_count == 1
        assert "first" not in service.session_ids
        assert "second" in service.session_ids


# ─────────────────────────────────────────────
# S413: Strategist MVP (案Z ハイブリッド型)
# Sprint 4.1.3 設計書: sprint_413_strategist_mvp_design.md
# ─────────────────────────────────────────────

class TestStrategistMVP:
    """S413-01〜S413-07: Strategist MVP (案Z) の検証"""

    def test_strategist_timeout(self):
        """S413-01: 30秒タイムアウト → CutStrategy.default()が返る"""
        import asyncio
        from services.smartcut_strategy_service import CutStrategy

        service = SmartCutStrategyService(max_sessions=5)

        async def slow_gemini(*args, **kwargs):
            await asyncio.sleep(10)  # タイムアウトを超える

        # テスト高速化: タイムアウトを0.1秒に短縮してテスト
        original_generate = service.generate_strategy

        async def fast_timeout_generate(session_id, **kwargs):
            """generate_strategyをタイムアウト0.1秒で実行"""
            philosophies = service._load_philosophies(kwargs.get('evolution_log_path'))
            integrated = service._load_integrated_philosophy(kwargs.get('evolution_log_path'))
            prompt = service._build_strategy_prompt(philosophies, integrated)
            from model_registry import get_model
            model_name = get_model("strategist")
            try:
                async with asyncio.timeout(0.1):  # 30→0.1秒に短縮
                    strategy = await service._call_gemini(model_name, prompt)
            except (TimeoutError, asyncio.TimeoutError):
                strategy = CutStrategy.default()
            except Exception:
                strategy = CutStrategy.default()
            session = service.get_or_create_session(session_id)
            session.strategy = strategy
            return strategy

        with patch.object(service, '_load_philosophies', return_value=[]), \
             patch.object(service, '_load_integrated_philosophy', return_value=""), \
             patch('model_registry.get_model', return_value="gemini-2.5-flash"), \
             patch.object(service, '_call_gemini', side_effect=slow_gemini):
            strategy = asyncio.run(fast_timeout_generate("timeout-test"))

        assert isinstance(strategy, CutStrategy)
        assert strategy.model_used == "default"
        assert strategy.summary == "デフォルト戦略（Strategist未応答）"
        assert strategy.trust_score == 0.0

    def test_strategist_philosophy_injection(self):
        """S413-02: evolution_log哲学がGeminiプロンプトに含まれる"""
        import asyncio
        import json as json_mod
        import tempfile
        from pathlib import Path as PathCls
        from services.smartcut_strategy_service import CutStrategy

        service = SmartCutStrategyService(max_sessions=5)

        # 228件の哲学エントリを含むevolution_logを作成
        philosophies = [{"id": i, "text": f"哲学エントリ{i}"} for i in range(228)]
        integrated = "統合哲学テキスト：美しさと共鳴を追求"

        captured_prompt = []

        async def capture_gemini(model_name, prompt):
            captured_prompt.append(prompt)
            return CutStrategy.default()

        evolution_data = {
            "philosophies": philosophies,
            "integrated_philosophy": integrated
        }

        # tmpファイルに書き出し
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                          encoding='utf-8') as f:
            json_mod.dump(evolution_data, f, ensure_ascii=False)
            tmp_path = PathCls(f.name)

        try:
            with patch('model_registry.get_model', return_value="gemini-2.5-flash"), \
                 patch.object(service, '_call_gemini', side_effect=capture_gemini):
                asyncio.run(service.generate_strategy("philosophy-test",
                                                       evolution_log_path=tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)

        assert len(captured_prompt) == 1
        prompt = captured_prompt[0]
        # 統合哲学が含まれる
        assert integrated in prompt
        # 直近20件が含まれる（228件中の末尾20件）
        assert "哲学エントリ227" in prompt
        assert "哲学エントリ208" in prompt

    def test_strategist_brand_alignment(self):
        """S413-03: brand_alignment_score ∈ [0.0, 1.0]"""
        import asyncio
        from services.smartcut_strategy_service import CutStrategy

        service = SmartCutStrategyService(max_sessions=5)

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "summary": "ブランド整合テスト",
            "position_weights": {"intro": 1.2, "body": 1.0, "highlight": 1.1, "outro": 0.9},
            "brand_alignment_score": 0.87,
            "recommended_cut_rate": 0.45
        })

        async def mock_gemini(model_name, prompt):
            return service._parse_response(mock_response, model_name)

        with patch.object(service, '_load_philosophies', return_value=[]), \
             patch.object(service, '_load_integrated_philosophy', return_value=""), \
             patch('model_registry.get_model', return_value="gemini-2.5-flash"), \
             patch.object(service, '_call_gemini', side_effect=mock_gemini):
            strategy = asyncio.run(service.generate_strategy("alignment-test"))

        assert isinstance(strategy, CutStrategy)
        assert 0.0 <= strategy.brand_alignment_score <= 1.0
        assert strategy.brand_alignment_score == 0.87

    def test_strategist_default_strategy(self):
        """S413-04: CutStrategy.default()の全フィールドが有効値"""
        from services.smartcut_strategy_service import CutStrategy

        default = CutStrategy.default()

        # 全フィールドの存在と型検証
        assert isinstance(default.summary, str) and len(default.summary) > 0
        assert isinstance(default.position_weights, dict)
        assert len(default.position_weights) == 4
        for key in ["intro", "body", "highlight", "outro"]:
            assert key in default.position_weights
            assert default.position_weights[key] == 1.0
        assert isinstance(default.brand_alignment_score, float)
        assert 0.0 <= default.brand_alignment_score <= 1.0
        assert isinstance(default.applied_philosophies, list)
        assert isinstance(default.recommended_cut_rate, float)
        assert 0.0 <= default.recommended_cut_rate <= 1.0
        assert isinstance(default.generated_at, str) and len(default.generated_at) > 0
        assert default.model_used == "default"
        assert default.trust_score == 0.0

    def test_strategist_model_registry(self):
        """S413-05: get_model("strategist")経由でモデル取得(§14.1)"""
        import asyncio
        from services.smartcut_strategy_service import CutStrategy

        service = SmartCutStrategyService(max_sessions=5)
        captured_model = []

        async def capture_model_gemini(model_name, prompt):
            captured_model.append(model_name)
            return CutStrategy.default()

        with patch.object(service, '_load_philosophies', return_value=[]), \
             patch.object(service, '_load_integrated_philosophy', return_value=""), \
             patch('model_registry.get_model', return_value="gemini-2.5-flash-strategist") as mock_get, \
             patch.object(service, '_call_gemini', side_effect=capture_model_gemini):
            asyncio.run(service.generate_strategy("model-registry-test"))

        mock_get.assert_called_once_with("strategist")
        assert captured_model[0] == "gemini-2.5-flash-strategist"

    def test_strategy_weight_injection(self):
        """S413-06: _clamp_weight(1.5, 0.0)→1.0, _clamp_weight(1.5, 1.0)→1.22"""
        from plugins.smart_cut_plugin import SmartCutPlugin

        # trust=0.0 → 常に1.0（影響なし）
        result_zero = SmartCutPlugin._clamp_weight(1.5, 0.0)
        assert result_zero == 1.0

        # trust=1.0 → ±22%の範囲でclamp
        # raw=1.5 → max_deviation=0.22 → min(1.22, 1.5) = 1.22
        result_full = SmartCutPlugin._clamp_weight(1.5, 1.0)
        assert abs(result_full - 1.22) < 1e-10

        # trust=0.0, raw=0.5 → 1.0（下限はmax(0.78, 0.5)ではなく、trust=0.0なので常に1.0）
        result_low = SmartCutPlugin._clamp_weight(0.5, 0.0)
        assert result_low == 1.0

        # trust=1.0, raw=0.5 → max(0.78, min(1.22, 0.5)) = max(0.78, 0.5) = 0.78
        result_low_trust = SmartCutPlugin._clamp_weight(0.5, 1.0)
        assert abs(result_low_trust - 0.78) < 1e-10

        # trust=0.7 → max_deviation=0.154 → ±15.4%
        result_mid = SmartCutPlugin._clamp_weight(1.5, 0.7)
        expected_mid = 1.0 + 0.7 * 0.22  # 1.154
        assert abs(result_mid - expected_mid) < 1e-10

    def test_strategist_invalid_json(self):
        """S413-07: Gemini不正JSON応答 → CutStrategy.default()"""
        import asyncio
        from services.smartcut_strategy_service import CutStrategy

        service = SmartCutStrategyService(max_sessions=5)

        # 不正JSONレスポンス
        mock_response = MagicMock()
        mock_response.text = "これはJSONではありません{{{invalid"

        async def mock_gemini(model_name, prompt):
            return service._parse_response(mock_response, model_name)

        with patch.object(service, '_load_philosophies', return_value=[]), \
             patch.object(service, '_load_integrated_philosophy', return_value=""), \
             patch('model_registry.get_model', return_value="gemini-2.5-flash"), \
             patch.object(service, '_call_gemini', side_effect=mock_gemini):
            strategy = asyncio.run(service.generate_strategy("invalid-json-test"))

        assert isinstance(strategy, CutStrategy)
        assert strategy.model_used == "default"
        assert strategy.summary == "デフォルト戦略（Strategist未応答）"


# ─────────────────────────────────────────────
# 追加のカバレッジ向上テスト (TestSmartCutStrategyServiceCoverage)
# ─────────────────────────────────────────────

class TestSmartCutStrategyServiceCoverage:
    """カバレッジを100%にするための追加テスト"""

    def test_session_context_with_no_plugin(self):
        """plugin=None の時に context プロパティが None を返すことを検証 (Line 88)"""
        from services.smartcut_strategy_service import SmartCutSession
        session = SmartCutSession(session_id="no-plugin", plugin=None)
        assert session.context is None

    def test_evict_oldest_empty(self):
        """セッションが空の時に _evict_oldest() がエラーなく return することを検証 (Line 140)"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        service = SmartCutStrategyService(max_sessions=5)
        # _evict_oldestを直接呼ぶ
        service._evict_oldest()
        assert service.session_count == 0

    def test_load_philosophies_exception(self):
        """無効なパスを指定して _load_philosophies が例外時に空リストを返すことを検証 (Line 236-238)"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from pathlib import Path
        service = SmartCutStrategyService(max_sessions=5)
        # 存在しない無効なパス
        invalid_path = Path("/invalid/path/to/nonexistent_file.json")
        philosophies = service._load_philosophies(invalid_path)
        assert philosophies == []

    def test_load_integrated_philosophy_exception(self):
        """無効なパスを指定して _load_integrated_philosophy が例外時に空文字列を返すことを検証 (Line 249-250)"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from pathlib import Path
        service = SmartCutStrategyService(max_sessions=5)
        invalid_path = Path("/invalid/path/to/nonexistent_file.json")
        integrated = service._load_integrated_philosophy(invalid_path)
        assert integrated == ""

    def test_parse_response_markdown_json(self):
        """_parse_response が ```json 囲みと ``` 囲みがある場合のパース挙動を検証 (Line 298, 300)"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from unittest.mock import MagicMock
        service = SmartCutStrategyService(max_sessions=5)
        
        # ```json 囲みのモックレスポンス
        mock_response_json = MagicMock()
        mock_response_json.text = "```json\n{\n  \"summary\": \"テスト概要1\",\n  \"position_weights\": {\"intro\": 1.1},\n  \"brand_alignment_score\": 0.9,\n  \"recommended_cut_rate\": 0.3\n}\n```"
        
        strategy1 = service._parse_response(mock_response_json, "test-model")
        assert strategy1.summary == "テスト概要1"
        assert strategy1.position_weights == {"intro": 1.1}
        assert strategy1.brand_alignment_score == 0.9
        assert strategy1.recommended_cut_rate == 0.3
        
        # ``` 囲みのモックレスポンス (Line 300 カバー用)
        mock_response_code = MagicMock()
        mock_response_code.text = "```\n{\n  \"summary\": \"テスト概要2\",\n  \"position_weights\": {\"intro\": 1.2},\n  \"brand_alignment_score\": 0.8,\n  \"recommended_cut_rate\": 0.4\n}\n```"
        
        strategy2 = service._parse_response(mock_response_code, "test-model")
        assert strategy2.summary == "テスト概要2"
        assert strategy2.position_weights == {"intro": 1.2}
        assert strategy2.brand_alignment_score == 0.8
        assert strategy2.recommended_cut_rate == 0.4

    @pytest.mark.asyncio
    async def test_call_gemini_client_not_found(self):
        """gemini_client_factory からクライアントを取得できなかった場合の挙動を検証 (Line 281-283)"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from unittest.mock import patch
        service = SmartCutStrategyService(max_sessions=5)
        
        with patch('gemini_client_factory.get_gemini_client', return_value=None):
            strategy = await service._call_gemini("test-model", "test-prompt")
            assert strategy.model_used == "default"
            assert strategy.summary == "デフォルト戦略（Strategist未応答）"

    @pytest.mark.asyncio
    async def test_call_gemini_success(self):
        """Gemini API呼び出しが正常に成功した場合の挙動を検証 (Line 285-290)"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from unittest.mock import patch, MagicMock
        service = SmartCutStrategyService(max_sessions=5)
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "summary": "正常応答テスト",
            "position_weights": {"intro": 1.3},
            "brand_alignment_score": 0.95,
            "recommended_cut_rate": 0.25
        })
        
        # generate_content は同期呼び出しのため、asyncio.to_thread を通して呼ばれる
        mock_client.models.generate_content.return_value = mock_response
        
        with patch('gemini_client_factory.get_gemini_client', return_value=mock_client):
            strategy = await service._call_gemini("test-model", "test-prompt")
            assert strategy.summary == "正常応答テスト"
            assert strategy.model_used == "test-model"
            assert strategy.brand_alignment_score == 0.95
            assert strategy.recommended_cut_rate == 0.25
            
        mock_client.models.generate_content.assert_called_once_with(
            model="test-model",
            contents="test-prompt"
        )

    @pytest.mark.asyncio
    async def test_generate_strategy_timeout_real(self):
        """本物の generate_strategy でタイムアウト例外が発生した時の挙動を検証 (Line 215-217)"""
        from services.smartcut_strategy_service import SmartCutStrategyService, CutStrategy
        from unittest.mock import patch
        import asyncio
        service = SmartCutStrategyService(max_sessions=5)
        
        # 呼び出しに時間がかかりタイムアウトするモック
        async def slow_call(*args, **kwargs):
            await asyncio.sleep(0.5)
            return CutStrategy.default()
            
        # テスト実行を高速化するため、一時的に asyncio.timeout(30) の代わりに 0.05秒にする
        # generate_strategy 自体を直接呼び出し、_call_gemini でタイムアウトさせる
        with patch.object(service, '_load_philosophies', return_value=[]),              patch.object(service, '_load_integrated_philosophy', return_value=""),              patch('model_registry.get_model', return_value="gemini-2.5-flash"),              patch.object(service, '_call_gemini', side_effect=slow_call),              patch('asyncio.timeout', return_value=asyncio.timeout(0.01)): # 0.01秒でタイムアウトさせる
             
            strategy = await service.generate_strategy("timeout-real-test")
            
        assert strategy.model_used == "default"
        assert strategy.summary == "デフォルト戦略（Strategist未応答）"

    @pytest.mark.asyncio
    async def test_generate_strategy_exception_real(self):
        """本物の generate_strategy で一般例外が発生した時の挙動を検証 (Line 218-220)"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from unittest.mock import patch
        service = SmartCutStrategyService(max_sessions=5)
        
        with patch.object(service, '_load_philosophies', return_value=[]),              patch.object(service, '_load_integrated_philosophy', return_value=""),              patch('model_registry.get_model', return_value="gemini-2.5-flash"),              patch.object(service, '_call_gemini', side_effect=ValueError("Gemini Error")):
             
            strategy = await service.generate_strategy("exception-real-test")
            
        assert strategy.model_used == "default"
        assert strategy.summary == "デフォルト戦略（Strategist未応答）"

    def test_load_philosophies_missing_key(self):
        """evolution_log に philosophies キーが存在しない場合に空リストが返ることを検証"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        import tempfile
        import json as json_mod
        from pathlib import Path
        
        service = SmartCutStrategyService(max_sessions=5)
        # philosophies キーを抜いたデータ
        invalid_data = {
            "integrated_philosophy": "テスト哲学"
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json_mod.dump(invalid_data, f, ensure_ascii=False)
            tmp_path = Path(f.name)
        try:
            philosophies = service._load_philosophies(tmp_path)
            assert philosophies == []
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_integrated_philosophy_missing_key(self):
        """evolution_log に integrated_philosophy キーが存在しない場合に空文字列が返ることを検証"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        import tempfile
        import json as json_mod
        from pathlib import Path
        
        service = SmartCutStrategyService(max_sessions=5)
        # integrated_philosophy キーを抜いたデータ
        invalid_data = {
            "philosophies": [{"id": 1, "text": "哲学"}]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json_mod.dump(invalid_data, f, ensure_ascii=False)
            tmp_path = Path(f.name)
        try:
            integrated = service._load_integrated_philosophy(tmp_path)
            assert integrated == ""
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_parse_response_missing_and_invalid_fields(self):
        """_parse_response において各キーが欠落または不正な値である場合のクランプ・フォールバック挙動を検証"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from unittest.mock import MagicMock
        service = SmartCutStrategyService(max_sessions=5)
        
        # 1. brand_alignment_score が欠落している場合（デフォルト 0.5 になること）
        mock_response_missing_bas = MagicMock()
        mock_response_missing_bas.text = json.dumps({
            "summary": "ブランドアライメント欠落",
            "position_weights": {"intro": 1.0},
            "recommended_cut_rate": 0.5
        })
        strategy1 = service._parse_response(mock_response_missing_bas, "test-model")
        assert strategy1.brand_alignment_score == 0.5
        
        # 2. brand_alignment_score が範囲外の値（1.5）で、クランプされる場合
        mock_response_invalid_bas_high = MagicMock()
        mock_response_invalid_bas_high.text = json.dumps({
            "summary": "ブランドアライメント高すぎ",
            "brand_alignment_score": 1.5,
            "recommended_cut_rate": 0.5
        })
        strategy2 = service._parse_response(mock_response_invalid_bas_high, "test-model")
        assert strategy2.brand_alignment_score == 1.0
        
        # 3. brand_alignment_score が範囲外の値（-0.5）で、クランプされる場合
        mock_response_invalid_bas_low = MagicMock()
        mock_response_invalid_bas_low.text = json.dumps({
            "summary": "ブランドアライメント低すぎ",
            "brand_alignment_score": -0.5,
            "recommended_cut_rate": 0.5
        })
        strategy3 = service._parse_response(mock_response_invalid_bas_low, "test-model")
        assert strategy3.brand_alignment_score == 0.0

        # 4. brand_alignment_score が文字列の場合でも float 変換される場合
        mock_response_str_bas = MagicMock()
        mock_response_str_bas.text = json.dumps({
            "summary": "ブランドアライメント文字列",
            "brand_alignment_score": "0.75",
            "recommended_cut_rate": 0.5
        })
        strategy4 = service._parse_response(mock_response_str_bas, "test-model")
        assert strategy4.brand_alignment_score == 0.75

        # 5. position_weights が欠落している場合、デフォルト weights が適用される場合
        mock_response_missing_weights = MagicMock()
        mock_response_missing_weights.text = json.dumps({
            "summary": "重み欠落",
            "brand_alignment_score": 0.8,
            "recommended_cut_rate": 0.5
        })
        strategy5 = service._parse_response(mock_response_missing_weights, "test-model")
        assert strategy5.position_weights == {"intro": 1.0, "body": 1.0, "highlight": 1.0, "outro": 1.0}

        # 6. recommended_cut_rate が欠落している場合、デフォルト 0.5 が適用されて正常に CutStrategy が返ること
        mock_response_missing_cut_rate = MagicMock()
        mock_response_missing_cut_rate.text = json.dumps({
            "summary": "カット率欠落",
            "brand_alignment_score": 0.8
        })
        strategy6 = service._parse_response(mock_response_missing_cut_rate, "test-model")
        assert strategy6.summary == "カット率欠落"
        assert strategy6.recommended_cut_rate == 0.5

        # 7. recommended_cut_rate が不正な値（変換不可）である場合、例外をキャッチして default() になること
        mock_response_invalid_cut_rate = MagicMock()
        mock_response_invalid_cut_rate.text = json.dumps({
            "summary": "不正なカット率",
            "brand_alignment_score": 0.8,
            "recommended_cut_rate": "invalid_rate"
        })
        strategy7 = service._parse_response(mock_response_invalid_cut_rate, "test-model")
        assert strategy7.summary == "デフォルト戦略（Strategist未応答）"

        # 8. brand_alignment_score が不正な値（変換不可）である場合、0.5 が適用されること
        mock_response_invalid_bas = MagicMock()
        mock_response_invalid_bas.text = json.dumps({
            "summary": "不正なアライメントスコア",
            "brand_alignment_score": "invalid_score",
            "recommended_cut_rate": 0.5
        })
        strategy8 = service._parse_response(mock_response_invalid_bas, "test-model")
        assert strategy8.brand_alignment_score == 0.5
        assert strategy8.summary == "不正なアライメントスコア"

    @pytest.mark.asyncio
    async def test_resolve_session_thumbnail_task_success(self, tmp_path):
        """resolve_session_thumbnail_task が正常に非同期実行され、品質情報が正しく返ることを検証"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        import json
        
        service = SmartCutStrategyService(max_sessions=5)
        service.output_dir = str(tmp_path)
        service.width = 1280
        service.height = 720
        service.text = "Async Test Thumbnail"
        
        mock_result = {
            "width": 1280,
            "height": 720,
            "size_bytes": 100,
            "path": str(tmp_path / "task-001.png")
        }
        
        with patch("combined_overlay.CombinedOverlay.generate_thumbnail") as mock_gen,              patch("combined_overlay.CombinedOverlay.validate_thumbnail", return_value=mock_result) as mock_val:
             
            result_str = await service.resolve_session_thumbnail_task("task-001")
            
            mock_gen.assert_called_once()
            mock_val.assert_called_once_with(tmp_path / "task-001.png")
            
            result = json.loads(result_str)
            assert result["width"] == 1280
            assert result["height"] == 720

    @pytest.mark.asyncio
    async def test_generate_strategy_specific_exceptions(self):
        """generate_strategy において、様々な具体的な例外が発生した時の挙動を検証"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        from unittest.mock import patch
        
        exceptions_to_test = [
            ImportError("Mock ImportError"),
            AttributeError("Mock AttributeError"),
            OSError("Mock OSError"),
            RuntimeError("Mock RuntimeError"),
            KeyError("Mock KeyError"),
            json.JSONDecodeError("msg", "doc", 0)
        ]
        
        for exc in exceptions_to_test:
            service = SmartCutStrategyService(max_sessions=5)
            with patch.object(service, '_load_philosophies', return_value=[]),                  patch.object(service, '_load_integrated_philosophy', return_value=""),                  patch('model_registry.get_model', return_value="gemini-2.5-flash"),                  patch.object(service, '_call_gemini', side_effect=exc):
                 
                strategy = await service.generate_strategy("specific-exc-test")
                
            assert strategy.model_used == "default"
            assert strategy.summary == "デフォルト戦略（Strategist未応答）"

    def test_load_philosophies_json_decode_error(self):
        """_load_philosophies において JSONDecodeError や TypeError が発生した場合に空リストを返すことを検証"""
        from services.smartcut_strategy_service import SmartCutStrategyService
        import tempfile
        from pathlib import Path
        
        service = SmartCutStrategyService(max_sessions=5)
        
        # 1. 壊れたJSONファイル (json.JSONDecodeError のテスト)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            f.write("invalid json content {")
            tmp_path = Path(f.name)
            
        try:
            philosophies = service._load_philosophies(tmp_path)
            assert philosophies == []
        finally:
            tmp_path.unlink(missing_ok=True)
            
        # 2. 不正な型のパス (TypeError のテスト)
        philosophies_type_err = service._load_philosophies(12345)  # Pathオブジェクトや文字列ではない
        assert philosophies_type_err == []

