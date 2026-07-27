"""
0%カバレッジモジュール脱出 — Batch 3 (フェーズA)

対象モジュール:
  1. wagamama_manager.py (118 stmts) — 11テスト
  2. settings_manager.py (63 stmts) — 9テスト
  3. subtitle_confirmation.py (103 stmts) — 10テスト
  4. routers/soul_router.py (89 stmts) — 15テスト (カバレッジ追加)
  5. routers/error_schemas.py (46 stmts) — 8テスト

合計: 53テスト
"""

import sys
import os
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# 1. WagamamaManager (11テスト)
# ============================================================

class TestWagamamaManager:
    """wagamama_manager.py の主要分岐テスト"""

    @pytest.fixture(autouse=True)
    def _setup_tmp_ledger(self, tmp_path, monkeypatch):
        """テスト用の一時台帳ファイルを設定"""
        import wagamama_manager as wm
        self._tmp_ledger = tmp_path / "wagamama_ledger.json"
        monkeypatch.setattr(wm, "LEDGER_FILE", self._tmp_ledger)
        monkeypatch.setattr(wm, "DATA_DIR", tmp_path)

    def test_wm_01_init_creates_file(self):
        """初期化時にファイルが生成される"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        assert self._tmp_ledger.exists()
        data = json.loads(self._tmp_ledger.read_text(encoding="utf-8"))
        assert "records" in data
        assert data["version"] == "1.0"

    def test_wm_02_create_experience_story(self):
        """新規ストーリー起票 — w_id が W-001 形式"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("テスト不満", detected_by="test")
        assert w_id == "W-001"
        record = mgr.get_record(w_id)
        assert record is not None
        assert record["lanes"]["experience"]["pain"] == "テスト不満"
        assert record["status"] == "investigating"

    def test_wm_03_link_council_session(self):
        """議会セッション紐付け"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("問題X")
        ok = mgr.link_council_session(w_id, "session-1", "log.json", {"summary": "解決策A"})
        assert ok is True
        record = mgr.get_record(w_id)
        assert record["status"] == "in_debate"
        assert record["lanes"]["experience"]["council"]["session_id"] == "session-1"

    def test_wm_04_link_council_not_found(self):
        """存在しないIDへの議会紐付け — False"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        assert mgr.link_council_session("W-999", "s1", "l.json", {}) is False

    def test_wm_05_resolve_story(self):
        """ストーリー解決"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("痛み")
        ok = mgr.resolve_story(w_id, "修正完了", emotion="満足")
        assert ok is True
        record = mgr.get_record(w_id)
        assert record["status"] == "resolved"
        assert record["lanes"]["experience"]["magic"] == "修正完了"

    def test_wm_06_resolve_not_found(self):
        """存在しないIDの解決 — False"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        assert mgr.resolve_story("W-999", "fix") is False

    def test_wm_07_set_youtube_video_id(self):
        """YouTube Video ID設定"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("テスト")
        ok = mgr.set_youtube_video_id(w_id, "abc123")
        assert ok is True
        assert mgr.get_record(w_id)["youtube_video_id"] == "abc123"

    def test_wm_08_enterprise_gate_go(self):
        """Enterprise Gate — Go判定"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("企画")
        result = mgr.enterprise_gate_check(w_id, predicted_ctr=5.0, min_threshold=3.0)
        assert result["is_go"] is True

    def test_wm_09_enterprise_gate_nogo(self):
        """Enterprise Gate — No-Go判定"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("企画")
        result = mgr.enterprise_gate_check(w_id, predicted_ctr=1.0, min_threshold=3.0)
        assert result["is_go"] is False

    def test_wm_10_quality_gaps(self):
        """品質ギャップ抽出"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("ギャップ")
        mgr.resolve_story(w_id, "修正済み")
        gaps = mgr.get_quality_gaps()
        assert len(gaps) >= 1
        assert gaps[0]["id"] == w_id

    def test_wm_11_link_manual_section(self):
        """マニュアルセクション紐付け — 品質ギャップ解消"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        w_id = mgr.create_experience_story("テスト")
        mgr.resolve_story(w_id, "修正済み")
        ok = mgr.link_manual_section(w_id, "§3.2")
        assert ok is True
        record = mgr.get_record(w_id)
        assert record["quality_gap"] is False
        assert record["manual_section"] == "§3.2"

    def test_wm_12_find_matching_story(self):
        """find_matching_story の動作をテスト"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        assert mgr.find_matching_story("some_topic") is None
        w_id = mgr.create_experience_story("痛みの声", feature_id="feat_test")
        assert mgr.find_matching_story("this is for feat_test topic") == w_id
        assert mgr.find_matching_story("other topic", tags=["feat_test"]) == w_id
        assert mgr.find_matching_story("痛みの声 topic") == w_id
        assert mgr.find_matching_story("completely unrelated topic") is None
        mgr.resolve_story(w_id, "解決")
        assert mgr.find_matching_story("this is for feat_test topic") is None

    def test_wm_13_add_distilled_knowledge(self):
        """add_distilled_knowledge の動作をテスト"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        k_id = mgr.add_distilled_knowledge("ctr_optimization", "use_red_thumbnail", confidence=0.95)
        assert k_id == "K-001"
        assert len(mgr.ledger_data["knowledge_base"]) == 1
        assert mgr.ledger_data["knowledge_base"][0]["topic"] == "ctr_optimization"

    def test_wm_14_auto_detect_manual_section(self, tmp_path, monkeypatch):
        """_auto_detect_manual_section の異常系と正常系をテスト"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        mgr.manual_path = tmp_path / "nonexistent_manual.md"
        assert mgr._auto_detect_manual_section({"feature_id": "feat_x"}) is None
        manual = tmp_path / "manual.md"
        manual.write_text("# Section feat_x\n", encoding="utf-8")
        mgr.manual_path = manual
        assert mgr._auto_detect_manual_section({"feature_id": ""}) is None
        assert mgr._auto_detect_manual_section({"feature_id": "feat_x"}) == "Section feat_x"
        assert mgr._auto_detect_manual_section({"feature_id": "feat_y"}) is None

    def test_wm_15_not_found_handling(self):
        """存在しないIDに対するハンドリングをテスト"""
        from wagamama_manager import WagamamaManager
        mgr = WagamamaManager()
        assert mgr.set_youtube_video_id("W-999", "vid") is False
        assert mgr.enterprise_gate_check("W-999", 5.0) == {"status": "error", "message": "Record not found"}
        assert mgr.link_manual_section("W-999", "sec") is False



# ============================================================
# 2. SettingsManager (9テスト)
# ============================================================

class TestSettingsManager:
    """settings_manager.py の主要分岐テスト"""

    @pytest.fixture(autouse=True)
    def _mock_branding(self, monkeypatch):
        """branding_manager をモック"""
        mock_bm = MagicMock()
        mock_bm.constitution = {
            "channel_name": "Test Channel",
            "target_audience": "テスト視聴者",
            "video_source_name": "",
        }
        mock_bm.user_model = {"name": "test_user"}
        mock_bm._save_json = MagicMock()

        mock_const_path = Path("/fake/constitution.json")
        monkeypatch.setattr("settings_manager.branding_manager", mock_bm)
        monkeypatch.setattr("settings_manager.CONSTITUTION_PATH", mock_const_path)
        self._mock_bm = mock_bm

    def test_sm_01_get_all_settings(self):
        """設定一覧取得"""
        from settings_manager import SettingsManager
        sm = SettingsManager()
        settings = sm.get_all_settings()
        assert "constitution" in settings
        assert "user_model" in settings
        assert "video_exists" in settings

    def test_sm_02_get_video_source(self):
        """動画ソースパス取得"""
        from settings_manager import SettingsManager
        sm = SettingsManager()
        path = sm.get_video_source()
        assert isinstance(path, str)
        assert "sample_raw.mp4" in path

    def test_sm_03_update_video_source_success(self, tmp_path):
        """動画ソース更新 — 成功"""
        from settings_manager import SettingsManager
        import settings_manager as sm_mod

        # 一時ファイルを作成
        src = tmp_path / "new_video.mp4"
        src.write_bytes(b"\x00" * 100)
        dest = tmp_path / "sample_raw.mp4"
        sm_mod.VIDEO_SRC_PATH = str(dest)

        sm = SettingsManager()
        result = sm.update_video_source(str(src), original_filename="my_video.mp4")
        assert result["status"] == "success"
        assert dest.exists()

    def test_sm_04_update_video_source_overwrites(self, tmp_path):
        """既存動画の上書き"""
        from settings_manager import SettingsManager
        import settings_manager as sm_mod

        dest = tmp_path / "sample_raw.mp4"
        dest.write_bytes(b"\x00" * 50)  # 既存ファイル
        src = tmp_path / "new.mp4"
        src.write_bytes(b"\xFF" * 200)
        sm_mod.VIDEO_SRC_PATH = str(dest)

        sm = SettingsManager()
        result = sm.update_video_source(str(src))
        assert result["status"] == "success"
        assert dest.stat().st_size == 200

    def test_sm_05_update_identity(self):
        """チャンネルID更新"""
        from settings_manager import SettingsManager
        sm = SettingsManager()
        result = sm.update_identity("NewChannel", "新しい視聴者")
        assert result["status"] == "success"
        assert self._mock_bm.constitution["channel_name"] == "NewChannel"

    def test_sm_06_export_soul_passport(self):
        """Soul Passportエクスポート"""
        from settings_manager import SettingsManager
        sm = SettingsManager()
        passport = sm.export_soul_passport()
        assert passport == {"name": "test_user"}

    def test_sm_07_reset_workspace(self, tmp_path):
        """ワークスペースリセット"""
        from settings_manager import SettingsManager
        import settings_manager as sm_mod

        video = tmp_path / "sample_raw.mp4"
        video.write_bytes(b"\x00")
        sm_mod.VIDEO_SRC_PATH = str(video)
        sm_mod.BASE_DIR = str(tmp_path)

        sm = SettingsManager()
        result = sm.reset_workspace()
        assert result["status"] == "success"

    def test_sm_08_reset_workspace_no_video(self, tmp_path):
        """動画なし時のリセット — エラーにならない"""
        from settings_manager import SettingsManager
        import settings_manager as sm_mod

        sm_mod.VIDEO_SRC_PATH = str(tmp_path / "nonexistent.mp4")
        sm_mod.BASE_DIR = str(tmp_path)

        sm = SettingsManager()
        result = sm.reset_workspace()
        assert result["status"] == "success"

    def test_sm_09_update_video_source_error(self, monkeypatch):
        """動画ソース更新 — エラー時"""
        from settings_manager import SettingsManager
        import settings_manager as sm_mod

        sm_mod.VIDEO_SRC_PATH = "/invalid/path/video.mp4"

        sm = SettingsManager()
        result = sm.update_video_source("/nonexistent/file.mp4")
        assert result["status"] == "error"


# ============================================================
# 3. SubtitleConfirmation (10テスト)
# ============================================================

class TestSubtitleConfirmation:
    """subtitle_confirmation.py の主要分岐テスト"""

    def test_sc_01_confirmation_item_dataclass(self):
        """ConfirmationItem データクラス作成"""
        from subtitle_confirmation import ConfirmationItem
        item = ConfirmationItem(
            id="test_001",
            timestamp="00:01:30",
            original_text="テスト",
            concern="テスト懸念",
            category="proper_noun",
        )
        assert item.id == "test_001"
        assert item.status == "pending"
        assert item.suggestion is None

    def test_sc_02_parse_response_json_block(self):
        """_parse_response — ```json ブロック形式"""
        from subtitle_confirmation import SubtitleConfirmationChecker
        checker = SubtitleConfirmationChecker()
        response = '```json\n[{"timestamp":"00:01:00","original_text":"テスト","concern":"固有名詞","category":"proper_noun","suggestion":"テスト2"}]\n```'
        items = checker._parse_response(response, "test")
        assert len(items) == 1
        assert items[0].category == "proper_noun"
        assert items[0].suggestion == "テスト2"

    def test_sc_03_parse_response_raw_json(self):
        """_parse_response — 生JSON形式"""
        from subtitle_confirmation import SubtitleConfirmationChecker
        checker = SubtitleConfirmationChecker()
        response = '[{"timestamp":"00:02:00","original_text":"ABC","concern":"不明","category":"uncertain"}]'
        items = checker._parse_response(response, "raw")
        assert len(items) == 1
        assert items[0].id == "raw_001"

    def test_sc_04_parse_response_empty(self):
        """_parse_response — 空レスポンス"""
        from subtitle_confirmation import SubtitleConfirmationChecker
        checker = SubtitleConfirmationChecker()
        items = checker._parse_response("Nothing here", "empty")
        assert items == []

    def test_sc_05_parse_response_invalid_json(self):
        """_parse_response — 不正JSON"""
        from subtitle_confirmation import SubtitleConfirmationChecker
        checker = SubtitleConfirmationChecker()
        items = checker._parse_response("[invalid json{}", "bad")
        assert items == []

    def test_sc_06_report_no_items(self):
        """レポート生成 — 確認項目なし"""
        from subtitle_confirmation import ConfirmationReportGenerator
        gen = ConfirmationReportGenerator()
        md = gen.generate("シーン1", [])
        assert "✅ 確認が必要な箇所はありません" in md

    def test_sc_07_report_with_items(self):
        """レポート生成 — 確認項目あり"""
        from subtitle_confirmation import ConfirmationReportGenerator, ConfirmationItem
        gen = ConfirmationReportGenerator()
        items = [
            ConfirmationItem(id="t_001", timestamp="00:01:00",
                           original_text="テスト文", concern="要確認",
                           category="uncertain", suggestion="修正案"),
        ]
        md = gen.generate("シーン2", items, screenshot_path="/img/test.png")
        assert "シーン2" in md
        assert "テスト文" in md
        assert "![プレビュー]" in md

    def test_sc_08_full_report(self):
        """完全レポート生成"""
        from subtitle_confirmation import ConfirmationReportGenerator, ConfirmationItem
        gen = ConfirmationReportGenerator()
        scenes = [
            {"name": "S1", "items": [], "screenshot": None},
            {"name": "S2", "items": [
                ConfirmationItem(id="s2_001", timestamp="00:05:00",
                               original_text="AAA", concern="BBB",
                               category="typo"),
            ]},
        ]
        md = gen.generate_full_report("テストレポート", scenes)
        assert "テストレポート" in md
        assert "操作方法" in md
        assert "S1" in md
        assert "S2" in md

    @pytest.mark.asyncio
    async def test_sc_09_analyze_subtitle(self, tmp_path):
        """analyze_subtitle — モックAPIで正常完了"""
        from subtitle_confirmation import SubtitleConfirmationChecker
        checker = SubtitleConfirmationChecker()

        # SRTファイル作成
        srt = tmp_path / "test.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:05,000\nテスト字幕\n", encoding="utf-8")

        # genai クライアントをモック
        mock_response = MagicMock()
        mock_response.text = '[]'

        mock_client = MagicMock()
        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_client.aio = mock_aio
        checker._client = mock_client

        items = await checker.analyze_subtitle(srt)
        assert items == []

    @pytest.mark.asyncio
    async def test_sc_10_analyze_subtitle_api_error(self, tmp_path):
        """analyze_subtitle — APIエラー時は空リスト"""
        from subtitle_confirmation import SubtitleConfirmationChecker
        checker = SubtitleConfirmationChecker()

        srt = tmp_path / "test.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:05,000\nテスト\n", encoding="utf-8")

        mock_client = MagicMock()
        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(side_effect=Exception("API Error"))
        mock_client.aio = mock_aio
        checker._client = mock_client

        items = await checker.analyze_subtitle(srt)
        assert items == []


# ============================================================
# 4. SoulRouter (15テストに拡張)
# ============================================================

class TestSoulRouter:
    """routers/soul_router.py のヘルパー関数 + ルーターテスト"""

    def test_sr_01_load_json_valid(self, tmp_path):
        """_load_json — 正常JSONロード"""
        from routers.soul_router import _load_json
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        result = _load_json(f)
        assert result["key"] == "value"

    def test_sr_02_load_json_missing(self, tmp_path):
        """_load_json — ファイル不在"""
        from routers.soul_router import _load_json
        result = _load_json(tmp_path / "missing.json")
        assert result == {}

    def test_sr_03_load_json_invalid(self, tmp_path):
        """_load_json — 不正JSON"""
        from routers.soul_router import _load_json
        f = tmp_path / "bad.json"
        f.write_text("{invalid", encoding="utf-8")
        result = _load_json(f)
        assert result == {}

    def test_sr_04_calculate_xp_empty(self):
        """_calculate_xp — 空エントリー"""
        from routers.soul_router import _calculate_xp
        assert _calculate_xp([]) == 0

    def test_sr_05_calculate_xp_basic(self):
        """_calculate_xp — 基本XP計算"""
        from routers.soul_router import _calculate_xp
        entries = [
            {"stat_changes": ["a", "b"], "philosophy_evolved": False},
            {"stat_changes": [], "philosophy_evolved": True},
        ]
        xp = _calculate_xp(entries)
        # entry1: 50 + 2*10 = 70, entry2: 50 + 0 + 100 = 150 → 合計220
        assert xp == 220

    def test_sr_06_determine_rank_dreamer(self):
        """_determine_rank — 低XPでDreamer"""
        from routers.soul_router import _determine_rank
        rank = _determine_rank(0)
        assert rank["level"] == "Dreamer"
        assert rank["next_rank"] is not None

    def test_sr_07_determine_rank_expert(self):
        """_determine_rank — 高XPでExpert"""
        from routers.soul_router import _determine_rank
        rank = _determine_rank(3000)
        assert rank["level"] == "Expert"

    def test_sr_08_determine_rank_legend(self):
        """_determine_rank — 最大XPでLegend"""
        from routers.soul_router import _determine_rank
        rank = _determine_rank(10000)
        assert rank["level"] == "Legend"
        assert rank["next_rank"] is None

    @pytest.mark.asyncio
    async def test_sr_09_dashboard_endpoint(self, tmp_path, monkeypatch):
        """get_soul_dashboard — 正常レスポンス"""
        from routers.soul_router import get_soul_dashboard
        import sys
        sr = sys.modules["routers.soul_router"]
        monkeypatch.setattr(sr, "HAS_ADK", False)

        # evolution_log モック
        evo = {
            "entries": [
                {"summary": "テスト", "insight": "学び",
                 "timestamp": 1714300000, "stat_changes": ["a"]},
            ],
            "philosophies": ["自然体が大事"],
            "decision_insights": [{"action": "approve"}],
            "last_updated": "2026-04-28T00:00:00",
        }
        constitution = {"brand_personality": {"keywords": ["自然", "親切"]}}

        evo_path = tmp_path / "evo.json"
        const_path = tmp_path / "const.json"
        evo_path.write_text(json.dumps(evo, ensure_ascii=False), encoding="utf-8")
        const_path.write_text(json.dumps(constitution, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(sr, "EVOLUTION_LOG_PATH", evo_path)
        monkeypatch.setattr(sr, "CONSTITUTION_PATH", const_path)

        result = await get_soul_dashboard()
        assert result["philosophy"]["current"] == "自然体が大事"
        assert result["rank"]["level"] == "Dreamer"  # XP=60
        assert result["statistics"]["total_sessions"] == 1
        assert result["statistics"]["approvals"] == 1

    @pytest.mark.asyncio
    async def test_sr_10_record_soul_event(self, tmp_path, monkeypatch):
        """record_soul_event — イベント記録"""
        from routers.soul_router import record_soul_event
        import sys
        sr = sys.modules["routers.soul_router"]

        evo_path = tmp_path / "evo.json"
        evo_path.write_text('{"entries": []}', encoding="utf-8")
        monkeypatch.setattr(sr, "EVOLUTION_LOG_PATH", evo_path)

        result = await record_soul_event({"summary": "テストイベント", "insight": "学習"})
        assert result["status"] == "recorded"
        assert result["entry"]["summary"] == "テストイベント"

        # ファイルに書き込まれているか確認
        saved = json.loads(evo_path.read_text(encoding="utf-8"))
        assert len(saved["entries"]) == 1

    @pytest.mark.asyncio
    async def test_sr_11_dashboard_empty_philosophies(self, tmp_path, monkeypatch):
        """get_soul_dashboard — 空の演出哲学および dict 型の演出哲学の処理"""
        from routers.soul_router import get_soul_dashboard
        import sys
        sr = sys.modules["routers.soul_router"]
        monkeypatch.setattr(sr, "HAS_ADK", False)

        # 空の philosophies
        evo = {
            "entries": [],
            "philosophies": [],
            "decision_insights": [],
            "last_updated": "2026-04-28T00:00:00",
        }
        constitution = {"brand_personality": {"keywords": []}}
        evo_path = tmp_path / "evo.json"
        const_path = tmp_path / "const.json"
        evo_path.write_text(json.dumps(evo, ensure_ascii=False), encoding="utf-8")
        const_path.write_text(json.dumps(constitution, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(sr, "EVOLUTION_LOG_PATH", evo_path)
        monkeypatch.setattr(sr, "CONSTITUTION_PATH", const_path)

        result = await get_soul_dashboard()
        assert result["philosophy"]["current"] == "まだ哲学が確立されていません"

        # dict 型の philosophy
        evo["philosophies"] = [{"text": "哲学辞書"}]
        evo_path.write_text(json.dumps(evo, ensure_ascii=False), encoding="utf-8")
        result = await get_soul_dashboard()
        assert result["philosophy"]["current"] == "哲学辞書"

    @pytest.mark.asyncio
    async def test_sr_12_dashboard_philosophies_history_limit(self, tmp_path, monkeypatch):
        """get_soul_dashboard — 演出哲学履歴が 5 件を超える場合の処理"""
        from routers.soul_router import get_soul_dashboard
        import sys
        sr = sys.modules["routers.soul_router"]
        monkeypatch.setattr(sr, "HAS_ADK", False)

        evo = {
            "entries": [],
            "philosophies": ["p1", "p2", "p3", "p4", "p5", "p6"],
            "decision_insights": [],
            "last_updated": "2026-04-28T00:00:00",
        }
        constitution = {"brand_personality": {"keywords": []}}
        evo_path = tmp_path / "evo.json"
        const_path = tmp_path / "const.json"
        evo_path.write_text(json.dumps(evo, ensure_ascii=False), encoding="utf-8")
        const_path.write_text(json.dumps(constitution, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(sr, "EVOLUTION_LOG_PATH", evo_path)
        monkeypatch.setattr(sr, "CONSTITUTION_PATH", const_path)

        result = await get_soul_dashboard()
        assert len(result["philosophy"]["history"]) == 5
        assert result["philosophy"]["history"] == ["p2", "p3", "p4", "p5", "p6"]

    @pytest.mark.asyncio
    async def test_sr_13_record_soul_event_exception(self, tmp_path, monkeypatch):
        """record_soul_event — 保存中のファイル例外処理"""
        from routers.soul_router import record_soul_event
        import sys
        sr = sys.modules["routers.soul_router"]

        evo_path = tmp_path / "evo.json"
        evo_path.write_text('{"entries": []}', encoding="utf-8")
        monkeypatch.setattr(sr, "EVOLUTION_LOG_PATH", evo_path)

        with patch("builtins.open", side_effect=IOError("Write failed")):
            result = await record_soul_event({"summary": "イベント", "insight": "学習"})
            assert result["status"] == "error"
            assert "Write failed" in result["error"]

    @pytest.mark.asyncio
    async def test_sr_14_load_json_http_exception(self, tmp_path, monkeypatch):
        """_load_json — HTTPException が適切に透過（raise）されることを確認"""
        from fastapi import HTTPException
        from routers.soul_router import _load_json

        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}', encoding="utf-8")

        with patch("json.load", side_effect=HTTPException(status_code=400, detail="HTTP Error")):
            with pytest.raises(HTTPException):
                _load_json(f)

    @pytest.mark.asyncio
    async def test_sr_15_record_soul_event_http_exception(self, tmp_path, monkeypatch):
        """record_soul_event — HTTPException が適切に透過（raise）されることを確認"""
        from fastapi import HTTPException
        from routers.soul_router import record_soul_event
        import sys
        sr = sys.modules["routers.soul_router"]

        evo_path = tmp_path / "evo.json"
        evo_path.write_text('{"entries": []}', encoding="utf-8")
        monkeypatch.setattr(sr, "EVOLUTION_LOG_PATH", evo_path)

        with patch("json.dump", side_effect=HTTPException(status_code=400, detail="HTTP Error")):
            with pytest.raises(HTTPException):
                await record_soul_event({"summary": "イベント", "insight": "学習"})

    def test_sr_16_load_json_decode_error(self, tmp_path):
        """_load_json — JSONDecodeError発生時に警告ログを出し空辞書を返すことを確認"""
        from routers.soul_router import _load_json
        f = tmp_path / "corrupted.json"
        f.write_text("invalid json string", encoding="utf-8")
        result = _load_json(f)
        assert result == {}

    def test_sr_17_load_json_os_error(self, tmp_path):
        """_load_json — OSError発生時に警告ログを出し空辞書を返すことを確認"""
        from routers.soul_router import _load_json
        from unittest.mock import patch
        f = tmp_path / "blocked.json"
        f.write_text("{}", encoding="utf-8")

        with patch("builtins.open", side_effect=OSError("Read blocked")):
            result = _load_json(f)
            assert result == {}


# ============================================================
# 5. ErrorSchemas (8テスト)
# ============================================================

class TestErrorSchemas:
    """routers/error_schemas.py の全分岐テスト"""

    def test_es_01_error_code_enum(self):
        """ErrorCode enum 定義確認"""
        from routers.error_schemas import ErrorCode
        assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"
        assert ErrorCode.AI_ERROR == "AI_ERROR"
        assert ErrorCode.FILE_ERROR == "FILE_ERROR"

    def test_es_02_error_detail_model(self):
        """ErrorDetail pydantic モデル"""
        from routers.error_schemas import ErrorDetail
        detail = ErrorDetail(message="テストエラー", field="name", code="E001")
        assert detail.message == "テストエラー"
        assert detail.field == "name"

    def test_es_03_standard_error_response(self):
        """StandardErrorResponse モデル"""
        from routers.error_schemas import StandardErrorResponse, ErrorCode
        resp = StandardErrorResponse(
            error="テスト",
            code=ErrorCode.VALIDATION_ERROR,
            timestamp="2026-04-28T00:00:00",
        )
        assert resp.success is False
        assert resp.code == "VALIDATION_ERROR"

    def test_es_04_create_error_response(self):
        """create_error_response — JSONレスポンス生成"""
        from routers.error_schemas import create_error_response, ErrorCode
        resp = create_error_response(
            code=ErrorCode.NOT_FOUND,
            message="見つかりません",
            status_code=404,
        )
        assert resp.status_code == 404
        body = json.loads(resp.body)
        assert body["error"] == "見つかりません"
        assert body["code"] == "NOT_FOUND"

    def test_es_05_create_error_response_with_details(self):
        """create_error_response — 詳細付き"""
        from routers.error_schemas import create_error_response, ErrorCode, ErrorDetail
        details = [ErrorDetail(message="フィールドが必要", field="name")]
        resp = create_error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message="バリデーションエラー",
            status_code=400,
            details=details,
            request_id="req-123",
        )
        body = json.loads(resp.body)
        assert body["request_id"] == "req-123"
        assert len(body["details"]) == 1

    @pytest.mark.asyncio
    async def test_es_06_global_exception_handler(self):
        """global_exception_handler — 500レスポンス"""
        from routers.error_schemas import global_exception_handler
        mock_request = MagicMock()
        mock_request.headers = {"X-Request-ID": "test-req"}
        resp = await global_exception_handler(mock_request, Exception("テスト例外"))
        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert body["code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_es_07_http_exception_handler(self):
        """http_exception_handler — ステータスコード変換"""
        from fastapi import HTTPException
        from routers.error_schemas import http_exception_handler
        mock_request = MagicMock()
        mock_request.headers = {}
        exc = HTTPException(status_code=404, detail="Not Found")
        resp = await http_exception_handler(mock_request, exc)
        assert resp.status_code == 404
        body = json.loads(resp.body)
        assert body["code"] == "NOT_FOUND"

    def test_es_08_register_error_handlers(self):
        """register_error_handlers — アプリ登録"""
        from routers.error_schemas import register_error_handlers
        mock_app = MagicMock()
        register_error_handlers(mock_app)
        assert mock_app.add_exception_handler.call_count == 2


# ============================================================
# 6. ApiVersioning (2テスト)
# ============================================================

class TestApiVersioning:
    """api_versioning.py のテスト"""

    def test_av_01_version_endpoint(self):
        """version エンドポイントのテスト"""
        from api_versioning import v1_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(v1_router)
        client = TestClient(app)

        response = client.get("/api/v1/version")
        assert response.status_code == 200
        data = response.json()
        assert data["api_version"] == "v1"
        assert data["app_version"] == "5.0.0"
        assert data["codename"] == "Trinity"
        assert "v1" in data["supported_versions"]
        assert data["deprecations"] == []

    def test_av_02_register_routes(self):
        """register_v1_routes を手動で呼び出すテスト"""
        from api_versioning import register_v1_routes
        from fastapi import APIRouter
        
        custom_router = APIRouter(prefix="/api/v2")
        register_v1_routes(custom_router)
        assert len(custom_router.routes) > 0

    def test_av_03_force_reload_coverage(self):
        """api_versioning モジュールを強制的に再ロードし、カバレッジ100%を保証する"""
        import sys
        import importlib
        
        # 既存のキャッシュをクリア
        if "api_versioning" in sys.modules:
            del sys.modules["api_versioning"]
            
        # 再インポートとリロード
        import api_versioning
        importlib.reload(api_versioning)
        
        # エンドポイントの登録処理を明示的に呼び出し
        from fastapi import APIRouter
        temp_router = APIRouter()
        api_versioning.register_v1_routes(temp_router)
        
        assert len(temp_router.routes) > 0

    def test_av_04_verify_all_mounted_routers(self):
        """register_v1_routes でマウントされるべきルーターがすべて含まれているかを検証する"""
        from api_versioning import register_v1_routes
        from fastapi import APIRouter
        
        custom_router = APIRouter()
        register_v1_routes(custom_router)
        
        # マウントされた各ルートのパスのプレフィクスを取得
        paths = {route.path for route in custom_router.routes}
        
        # 期待される prefix または主要エンドポイントのキーワード
        expected_prefixes = [
            "/api/quality",
            "/api/preview",
            "/api/usage",
            "/api/youtube",
            "/api/smartcut",
            "/api/shorts",
            "/api/pipeline",
            "/themes",
            "/soul",
            "/mcp"
        ]
        
        for prefix in expected_prefixes:
            assert any(p.startswith(prefix) for p in paths), f"Expected prefix '{prefix}' was not mounted in api_versioning.py"


    def test_av_05_register_routes_mounting_failure(self):
        """register_v1_routes での例外発生時に、TDRへの登録が行われ、かつ例外が再スローされることを検証"""
        from api_versioning import register_v1_routes
        from fastapi import APIRouter
        from unittest.mock import patch, MagicMock

        custom_router = APIRouter()
        with patch.object(custom_router, 'include_router', side_effect=ValueError("Simulated mounting crash")):
            with patch('agents.memory.technical_debt.TechnicalDebtStore') as mock_tdr_store_cls:
                mock_store = MagicMock()
                mock_tdr_store_cls.return_value = mock_store
                
                with pytest.raises(ValueError, match="Simulated mounting crash"):
                    register_v1_routes(custom_router)
                
                mock_store.register_debt.assert_called_once()
                args, kwargs = mock_store.register_debt.call_args
                assert kwargs.get("category") == "CRITICAL_ROUTER"
                assert "api_versioning.py" in kwargs.get("file_path")
                assert "mounting_failure" in kwargs.get("tags")

    @pytest.mark.asyncio
    async def test_av_06_version_endpoint_failure(self):
        """get_api_version エンドポイントで例外が発生した際、TDR登録されHTTPExceptionが返ることを検証"""
        from api_versioning import get_api_version
        from fastapi import HTTPException
        from unittest.mock import patch, MagicMock

        with patch('api_versioning._get_version_metadata', side_effect=RuntimeError("Simulated version error")):
            with patch('agents.memory.technical_debt.TechnicalDebtStore') as mock_tdr_store_cls:
                mock_store = MagicMock()
                mock_tdr_store_cls.return_value = mock_store

                with pytest.raises(HTTPException) as exc_info:
                    await get_api_version()
                
                assert exc_info.value.status_code == 500
                assert "Simulated version error" in exc_info.value.detail
                
                mock_store.register_debt.assert_called_once()
                args, kwargs = mock_store.register_debt.call_args
                assert kwargs.get("category") == "CRITICAL_ROUTER"
                assert "version_endpoint" in kwargs.get("tags")


    def test_av_07_register_routes_http_exception(self):
        """register_v1_routes で HTTPException が発生した際、そのまま raise されること"""
        from api_versioning import register_v1_routes
        from fastapi import APIRouter, HTTPException
        from unittest.mock import patch

        custom_router = APIRouter()
        with patch.object(custom_router, 'include_router', side_effect=HTTPException(status_code=400, detail="HTTP Error")):
            with pytest.raises(HTTPException) as exc_info:
                register_v1_routes(custom_router)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_av_08_version_endpoint_http_exception(self):
        """get_api_version で HTTPException が発生した際、そのまま raise されること"""
        from api_versioning import get_api_version
        from fastapi import HTTPException
        from unittest.mock import patch

        with patch('api_versioning._get_version_metadata', side_effect=HTTPException(status_code=403, detail="Forbidden")):
            with pytest.raises(HTTPException) as exc_info:
                await get_api_version()
            assert exc_info.value.status_code == 403

    def test_av_09_register_routes_tdr_registration_failure(self):
        """register_v1_routes で例外が発生し、かつ TDR 登録に失敗したときのフォールバックと元の例外の再スロー"""
        from api_versioning import register_v1_routes
        from fastapi import APIRouter
        from unittest.mock import patch, MagicMock

        custom_router = APIRouter()
        with patch.object(custom_router, 'include_router', side_effect=ValueError("Simulated mounting crash")):
            with patch('agents.memory.technical_debt.TechnicalDebtStore') as mock_tdr_store_cls:
                mock_tdr_store_cls.side_effect = RuntimeError("TDR connection failed")
                
                with patch('api_versioning.logger.error') as mock_logger_error:
                    with pytest.raises(ValueError, match="Simulated mounting crash"):
                        register_v1_routes(custom_router)
                    
                    assert mock_logger_error.call_count >= 2
                    mock_logger_error.assert_any_call("Failed to register technical debt for mounting error: TDR connection failed")

    @pytest.mark.asyncio
    async def test_av_10_version_endpoint_tdr_registration_failure(self):
        """get_api_version で例外が発生し、かつ TDR 登録に失敗したときのフォールバックと HTTPException(500) スロー"""
        from api_versioning import get_api_version
        from fastapi import HTTPException
        from unittest.mock import patch, MagicMock

        with patch('api_versioning._get_version_metadata', side_effect=RuntimeError("Simulated version error")):
            with patch('agents.memory.technical_debt.TechnicalDebtStore') as mock_tdr_store_cls:
                mock_store = MagicMock()
                mock_store.register_debt.side_effect = RuntimeError("TDR write error")
                mock_tdr_store_cls.return_value = mock_store

                with patch('api_versioning.logger.error') as mock_logger_error:
                    with pytest.raises(HTTPException) as exc_info:
                        await get_api_version()
                    
                    assert exc_info.value.status_code == 500
                    assert "Simulated version error" in exc_info.value.detail
                    
                    mock_logger_error.assert_any_call("Failed to register technical debt for version endpoint error: TDR write error")
