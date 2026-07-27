"""
test_adk_soul_integration.py — ADK / Soul Passport 結合テスト

目的:
- HAS_ADK=True/False それぞれのモック環境下で /soul/dashboard などの主要エンドポイントが正常に応答することを確認
- 魂の永続化ファイル（evolution_log.json, constitution.json）が適切に読み書き・更新されることを検証する
- 結合部のカバレッジ 100% 維持を保証する
"""

import json
import sys
import os
import pytest
import builtins
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

# backend を sys.path に追加
backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import routers.soul_router
import sys
soul_router = sys.modules['routers.soul_router']


@pytest.fixture
def mock_soul_paths(tmp_path):
    """魂の永続化ファイルを一時ディレクトリに差し替えるフィクスチャ"""
    test_evo_log = tmp_path / "evolution_log.json"
    test_constitution = tmp_path / "constitution.json"

    # 初期データを書き込み (philosophies を 6 件以上にして len(philosophies) > 5 ブランチをカバー)
    initial_log = {
        "entries": [
            {
                "summary": "初期セッション",
                "insight": "最初の気づき",
                "timestamp": 1700000000.0,
                "stat_changes": ["XP +50"]
            }
        ],
        "philosophies": [
            {"text": f"演出哲学 {i}", "timestamp": 1700000000.0 + i} for i in range(6)
        ],
        "decision_insights": [
            {"action": "approve", "reason": "good"},
            {"action": "reject", "reason": "bad"} # reject も追加してジェネレータ条件をカバー
        ],
        "last_updated": "2026-05-23T00:00:00"
    }
    test_evo_log.write_text(
        json.dumps(initial_log, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    initial_const = {
        "brand_personality": {
            "keywords": ["creative", "bold"]
        }
    }
    test_constitution.write_text(
        json.dumps(initial_const, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 元のパスを退避し、モックで差し替え
    orig_evo = soul_router.EVOLUTION_LOG_PATH
    orig_const = soul_router.CONSTITUTION_PATH

    soul_router.EVOLUTION_LOG_PATH = test_evo_log
    soul_router.CONSTITUTION_PATH = test_constitution

    yield test_evo_log, test_constitution

    # 元に戻す
    soul_router.EVOLUTION_LOG_PATH = orig_evo
    soul_router.CONSTITUTION_PATH = orig_const


@pytest.fixture
def test_client():
    """テスト用 FastAPI TestClient"""
    from fastapi import FastAPI
    from routers.soul_router import router as soul_router_obj
    from routers.collaboration import router as collab_router_obj

    app = FastAPI()
    app.include_router(soul_router_obj)
    app.include_router(collab_router_obj)
    return TestClient(app, raise_server_exceptions=True)


class TestAdkSoulIntegration:
    """ADK / Soul Passport 結合テストクラス"""

    @pytest.mark.asyncio
    async def test_has_adk_true_integration(self, test_client, mock_soul_paths):
        """HAS_ADK=True のモック環境下で、議会セッションが正常に動作しダッシュボードに反映されること"""
        mock_runner = MagicMock()
        mock_session_service = AsyncMock()
        mock_session = MagicMock()
        mock_session.state = {"council_synthesis": "ADKが生成した統合演出哲学。"}
        mock_session_service.create_session.return_value = mock_session
        mock_session_service.get_session.return_value = mock_session
        mock_runner.session_service = mock_session_service

        event = MagicMock()
        event.is_final_response.return_value = True
        part = MagicMock()
        part.text = "最終的な提案レポートです。"
        event.content.parts = [part]

        class AsyncEventIterator:
            def __init__(self, events):
                self.events = events
                self.index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index < len(self.events):
                    val = self.events[self.index]
                    self.index += 1
                    return val
                else:
                    raise StopAsyncIteration

        mock_runner.run_async.return_value = AsyncEventIterator([event])

        # google.adk 関連モジュールをモックし、正常系（HAS_ADK=True）をシミュレート
        with patch.dict("sys.modules", {
            "google.adk.runners": MagicMock(InMemoryRunner=MagicMock(return_value=mock_runner)),
            "google.adk.sessions": MagicMock(InMemorySessionService=MagicMock(return_value=mock_session_service)),
            "google.adk.agents.run_config": MagicMock(),
            "google.genai": MagicMock(),
            "google.genai.types": MagicMock(),
            "agents.adk_agent_template": MagicMock()
        }):
            # 議会セッションを起動するエンドポイントを呼び出し
            resp = test_client.post(
                "/api/council/session",
                json={
                    "query": "演出哲学の改善について",
                    "council_mode": "post_production"
                }
            )

            # 正常応答を検証
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert data["synthesis"] == "最終的な提案レポートです。"

            # 魂のダッシュボードエンドポイントが正常応答することを確認
            dash_resp = test_client.get("/soul/dashboard")
            assert dash_resp.status_code == 200
            dash_data = dash_resp.json()
            assert "philosophy" in dash_data
            assert "rank" in dash_data

    @pytest.mark.asyncio
    async def test_has_adk_false_integration(self, test_client, mock_soul_paths):
        """HAS_ADK=False（モジュール不在によるフォールバック）のモック環境下で、安全にフォールバック応答を返すこと"""
        # google.adk 関連モジュールを sys.modules から除外（Noneに設定）し、フォールバック（HAS_ADK=False）をシミュレート
        with patch.dict("sys.modules", {
            "google.adk.runners": None,
            "google.adk.sessions": None,
            "google.adk": None,
            "google.adk.agents.run_config": None
        }):
            # 議会セッションを起動
            resp = test_client.post(
                "/api/council/session",
                json={
                    "query": "演出哲学の改善について",
                    "council_mode": "post_production"
                }
            )

            # 500エラーでクラッシュせず、フォールバック応答（status: error）を返すこと
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "error"
            assert "synthesis" in data

            # ダッシュボードエンドポイントが影響を受けず、正常応答し続けること
            dash_resp = test_client.get("/soul/dashboard")
            assert dash_resp.status_code == 200

    def test_soul_endpoints_read_write(self, test_client, mock_soul_paths, monkeypatch):
        """魂の主要エンドポイント（dashboard, philosophy, chronicle, record）の読み書き・更新検証"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)
        test_evo_log, test_constitution = mock_soul_paths

        # 1. 魂のダッシュボード読み込み（GET /soul/dashboard）
        resp = test_client.get("/soul/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["philosophy"]["current"] == "演出哲学 5"
        assert "industry_benchmarks" in data
        assert data["brand_keywords"] == ["creative", "bold"]

        # 2. 演出哲学一覧の取得（GET /soul/philosophy）
        resp = test_client.get("/soul/philosophy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 6
        assert data["latest"]["text"] == "演出哲学 5"

        # 3. 成長クロニクルの取得（GET /soul/chronicle）
        resp = test_client.get("/soul/chronicle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["chronicle"][0]["summary"] == "初期セッション"

        # 4. 新規イベントの書き込み・永続化検証（POST /soul/record）
        record_resp = test_client.post(
            "/soul/record",
            json={
                "summary": "新規の演出改善セッション",
                "insight": "よりビビッドな色調を推奨する",
                "stat_changes": ["XP +100"],
                "philosophy_evolved": True
            }
        )
        assert record_resp.status_code == 200
        record_data = record_resp.json()
        assert record_data["status"] == "recorded"
        assert record_data["entry"]["summary"] == "新規の演出改善セッション"

        # 5. ファイルが適切に永続化され、読み込みに反映されているか
        with open(test_evo_log, "r", encoding="utf-8") as f:
            saved_log = json.load(f)
        assert len(saved_log["entries"]) == 2
        assert saved_log["entries"][-1]["summary"] == "新規の演出改善セッション"

        # ダッシュボードでのXP再計算およびランク判定の更新検証
        resp = test_client.get("/soul/dashboard")
        data = resp.json()
        assert data["statistics"]["total_sessions"] == 2
        # 初期セッション (基本50+stat_changes_len(1)*10=60) + 新規セッション (基本50+stat_changes_len(1)*10+philosophy_evolved(100)=160) = 220 XP
        assert data["rank"]["xp"] == 220
        # XP >= 200 なのでランクが Scout にアップしていることを確認
        assert data["rank"]["level"] == "Scout"

        # 6. XP >= 10000 の最高ランク到達時の挙動（next_rank is None ブランチ）をカバーする検証
        high_xp_log = {
            "entries": [
                {
                    "summary": "レジェンド演出セッション",
                    "timestamp": 1700000000.0,
                    "stat_changes": [f"XP +{i}" for i in range(1000)] # 1000 * 10 = 10000 XP
                }
            ]
        }
        test_evo_log.write_text(json.dumps(high_xp_log, ensure_ascii=False), encoding="utf-8")
        resp = test_client.get("/soul/dashboard")
        data = resp.json()
        assert data["rank"]["level"] == "Legend"
        assert data["rank"]["next_rank"] is None

    def test_soul_load_json_exceptions(self, test_client, mock_soul_paths, monkeypatch):
        """JSON読み込み・書き込み時の例外発生時に安全に動作することの検証"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)
        test_evo_log, test_constitution = mock_soul_paths

        # JSON ファイルが破損している場合
        test_evo_log.write_text("{broken json", encoding="utf-8")
        
        # 警告ログを出力しつつ、空の辞書としてフォールバックし、500エラーで落ちないこと
        resp = test_client.get("/soul/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["philosophy"]["total_philosophies"] == 0

        # latest_philosophy が辞書ではないパターン（文字列）の検証
        test_evo_log.write_text(json.dumps({
            "philosophies": ["単なる文字列の哲学"]
        }, ensure_ascii=False), encoding="utf-8")
        resp = test_client.get("/soul/dashboard")
        assert resp.json()["philosophy"]["current"] == "単なる文字列の哲学"

        # latest_philosophy が辞書で、かつ text キーがないパターンの検証
        test_evo_log.write_text(json.dumps({
            "philosophies": [{"unknown_key": "値"}]
        }, ensure_ascii=False), encoding="utf-8")
        resp = test_client.get("/soul/dashboard")
        assert "unknown_key" in resp.json()["philosophy"]["current"]

        # ファイル書き込み権限がないなどの書き込みエラー時の挙動
        # (書き込み時に例外を発生させるモック)
        with patch("builtins.open", side_effect=IOError("Permission Denied")):
            record_resp = test_client.post(
                "/soul/record",
                json={"summary": "書き込み失敗テスト"}
            )
            assert record_resp.status_code == 200
            data = record_resp.json()
            assert data["status"] == "error"
            assert "Permission Denied" in data["error"]

    def test_soul_load_json_http_exception(self, test_client, mock_soul_paths, monkeypatch):
        """_load_json 内で HTTPException が発生した場合、そのまま呼び出し元に伝播することの検証"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)
        # open で HTTPException を発生させて 37-38 行目をカバー。
        # FastAPIのハンドラで処理されてレスポンス400が返ることをアサートする。
        with patch("builtins.open", side_effect=HTTPException(status_code=400, detail="HTTP Error")):
            resp = test_client.get("/soul/dashboard")
            assert resp.status_code == 400

    def test_soul_record_http_exception(self, test_client, mock_soul_paths, monkeypatch):
        """record_soul_event 内で HTTPException が発生した場合、そのまま呼び出し元に伝播することの検証"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)
        # json.dump で HTTPException を発生させて 244-245 行目をカバー。
        # FastAPIのハンドラで処理されてレスポンス400が返ることをアサートする。
        with patch("json.dump", side_effect=HTTPException(status_code=400, detail="HTTP Dump Error")):
            resp = test_client.post("/soul/record", json={"summary": "HTTP例外テスト"})
            assert resp.status_code == 400


    @pytest.mark.asyncio
    async def test_soul_dashboard_save_http_exception(self, test_client, mock_soul_paths):
        """dashboard保存時にHTTPExceptionが発生した場合、そのまま伝播することの検証 (L130-131)"""
        mock_runner = MagicMock()
        mock_session_service = AsyncMock()
        mock_session = MagicMock()
        mock_session.state = {"council_synthesis": "ADKが生成した統合演出哲学。"}
        mock_session_service.create_session.return_value = mock_session
        mock_session_service.get_session.return_value = mock_session
        mock_runner.session_service = mock_session_service

        event = MagicMock()
        event.is_final_response.return_value = True
        part = MagicMock()
        part.text = "最終的な提案レポートです。"
        event.content.parts = [part]

        class AsyncEventIterator:
            def __init__(self, events):
                self.events = events
                self.index = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self.index < len(self.events):
                    val = self.events[self.index]
                    self.index += 1
                    return val
                else:
                    raise StopAsyncIteration

        mock_runner.run_async.return_value = AsyncEventIterator([event])

        with patch.dict("sys.modules", {
            "google.adk.runners": MagicMock(InMemoryRunner=MagicMock(return_value=mock_runner)),
            "google.adk.sessions": MagicMock(InMemorySessionService=MagicMock(return_value=mock_session_service)),
            "google.adk.agents.run_config": MagicMock(),
            "google.genai": MagicMock(),
            "google.genai.types": MagicMock(),
            "agents.adk_agent_template": MagicMock()
        }):
            with patch("json.dump", side_effect=HTTPException(status_code=400, detail="Dump HTTP Error")):
                resp = test_client.get("/soul/dashboard")
                assert resp.status_code == 400
                assert "Dump HTTP Error" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_soul_dashboard_save_exception(self, test_client, mock_soul_paths):
        """dashboard保存時に一般Exceptionが発生した場合、500エラーとしてフォールバックすることの検証 (L132-134)"""
        mock_runner = MagicMock()
        mock_session_service = AsyncMock()
        mock_session = MagicMock()
        mock_session.state = {"council_synthesis": "ADKが生成した統合演出哲学。"}
        mock_session_service.create_session.return_value = mock_session
        mock_session_service.get_session.return_value = mock_session
        mock_runner.session_service = mock_session_service

        event = MagicMock()
        event.is_final_response.return_value = True
        part = MagicMock()
        part.text = "最終的な提案レポートです。"
        event.content.parts = [part]

        class AsyncEventIterator:
            def __init__(self, events):
                self.events = events
                self.index = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self.index < len(self.events):
                    val = self.events[self.index]
                    self.index += 1
                    return val
                else:
                    raise StopAsyncIteration

        mock_runner.run_async.return_value = AsyncEventIterator([event])

        with patch.dict("sys.modules", {
            "google.adk.runners": MagicMock(InMemoryRunner=MagicMock(return_value=mock_runner)),
            "google.adk.sessions": MagicMock(InMemorySessionService=MagicMock(return_value=mock_session_service)),
            "google.adk.agents.run_config": MagicMock(),
            "google.genai": MagicMock(),
            "google.genai.types": MagicMock(),
            "agents.adk_agent_template": MagicMock()
        }):
            with patch("json.dump", side_effect=OSError("Dump Write Error")):
                resp = test_client.get("/soul/dashboard")
                assert resp.status_code == 500
                assert "Failed to save log" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_soul_dashboard_council_http_exception(self, test_client, mock_soul_paths):
        """dashboard内のADK連携処理でHTTPExceptionが発生した場合、そのまま伝播することの検証 (L135-136)"""
        mock_runner = MagicMock()
        mock_session_service = AsyncMock()
        mock_session = MagicMock()
        mock_session_service.create_session.return_value = mock_session
        mock_session_service.get_session.return_value = mock_session
        mock_runner.session_service = mock_session_service

        with patch.dict("sys.modules", {
            "google.adk.runners": MagicMock(InMemoryRunner=MagicMock(return_value=mock_runner)),
            "google.adk.sessions": MagicMock(InMemorySessionService=MagicMock(return_value=mock_session_service)),
            "google.adk.agents.run_config": MagicMock(),
            "google.genai": MagicMock(),
            "google.genai.types": MagicMock(),
            "agents.adk_agent_template": MagicMock()
        }):
            with patch("agents.council_graph.run_council", side_effect=HTTPException(status_code=403, detail="ADK Forbidden")):
                resp = test_client.get("/soul/dashboard")
                assert resp.status_code == 403
                assert "ADK Forbidden" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_soul_dashboard_council_exception(self, test_client, mock_soul_paths):
        """dashboard内のADK連携処理で一般Exceptionが発生した場合、500エラーとしてフォールバックすることの検証 (L137-139)"""
        mock_runner = MagicMock()
        mock_session_service = AsyncMock()
        mock_session = MagicMock()
        mock_session_service.create_session.return_value = mock_session
        mock_session_service.get_session.return_value = mock_session
        mock_runner.session_service = mock_session_service

        with patch.dict("sys.modules", {
            "google.adk.runners": MagicMock(InMemoryRunner=MagicMock(return_value=mock_runner)),
            "google.adk.sessions": MagicMock(InMemorySessionService=MagicMock(return_value=mock_session_service)),
            "google.adk.agents.run_config": MagicMock(),
            "google.genai": MagicMock(),
            "google.genai.types": MagicMock(),
            "agents.adk_agent_template": MagicMock()
        }):
            with patch("agents.council_graph.run_council", side_effect=RuntimeError("Council Critical Fail")):
                resp = test_client.get("/soul/dashboard")
                assert resp.status_code == 500
                assert "ADK integration failed" in resp.json()["detail"]

    def test_soul_load_json_path_not_exists(self, test_client, mock_soul_paths, monkeypatch):
        """JSONファイルが存在しない場合、_load_json が安全に空辞書を返し、ダッシュボードが正常に応答すること"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)
        test_evo_log, test_constitution = mock_soul_paths

        # ファイルを削除して存在しない状態にする
        if test_evo_log.exists():
            test_evo_log.unlink()
        if test_constitution.exists():
            test_constitution.unlink()

        resp = test_client.get("/soul/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["philosophy"]["total_philosophies"] == 0
        assert data["rank"]["xp"] == 0
        assert data["rank"]["level"] == "Dreamer"
        assert data["brand_keywords"] == []

    def test_soul_endpoints_empty_data(self, test_client, mock_soul_paths, monkeypatch):
        """ログデータが空（キーが存在しない、または空リスト）の場合の各エンドポイントの挙動検証"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)
        test_evo_log, test_constitution = mock_soul_paths

        # 空のJSONを書き込む
        test_evo_log.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

        # 演出哲学一覧
        resp = test_client.get("/soul/philosophy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["latest"] is None

        # 成長クロニクル
        resp = test_client.get("/soul/chronicle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["chronicle"] == []

    def test_determine_rank_boundaries(self):
        """_determine_rank の各ランク境界値および next_rank の計算ロジック検証"""
        from routers.soul_router import _determine_rank

        # Dreamer (0 - 199 XP)
        rank_0 = _determine_rank(0)
        assert rank_0["level"] == "Dreamer"
        assert rank_0["next_rank"]["name"] == "Scout"
        assert rank_0["next_rank"]["threshold"] == 200
        assert rank_0["next_rank"]["remaining"] == 200

        rank_199 = _determine_rank(199)
        assert rank_199["level"] == "Dreamer"
        assert rank_199["next_rank"]["remaining"] == 1

        # Scout (200 - 499 XP)
        rank_200 = _determine_rank(200)
        assert rank_200["level"] == "Scout"
        assert rank_200["next_rank"]["name"] == "Apprentice"
        assert rank_200["next_rank"]["threshold"] == 500

        # Apprentice (500 - 999 XP)
        rank_500 = _determine_rank(500)
        assert rank_500["level"] == "Apprentice"

        # Creator (1000 - 1999 XP)
        rank_1000 = _determine_rank(1000)
        assert rank_1000["level"] == "Creator"

        # Expert (2000 - 4999 XP)
        rank_2000 = _determine_rank(2000)
        assert rank_2000["level"] == "Expert"

        # Master (5000 - 9999 XP)
        rank_5000 = _determine_rank(5000)
        assert rank_5000["level"] == "Master"

        # Legend (10000+ XP)
        rank_10000 = _determine_rank(10000)
        assert rank_10000["level"] == "Legend"
        assert rank_10000["next_rank"] is None

    def test_safe_load_for_writing_exceptions(self, mock_soul_paths):
        """_safe_load_for_writing が破損JSONやOSエラー時に適切にHTTPException(500)を投げること"""
        from routers.soul_router import _safe_load_for_writing
        test_evo_log, _ = mock_soul_paths

        # 1. 破損JSON
        test_evo_log.write_text("{corrupted json", encoding="utf-8")
        with pytest.raises(HTTPException) as exc_info:
            _safe_load_for_writing(test_evo_log)
        assert exc_info.value.status_code == 500
        assert "is corrupted and cannot be updated safely" in exc_info.value.detail

        # 2. OS例外
        with patch("builtins.open", side_effect=IOError("Mocked OS Error")):
            with pytest.raises(HTTPException) as exc_info_os:
                _safe_load_for_writing(test_evo_log)
            assert exc_info_os.value.status_code == 500
            assert "Failed to load data file" in exc_info_os.value.detail

    def test_record_soul_event_validation(self, test_client, mock_soul_paths, monkeypatch):
        """record_soul_event において入力 event のバリデーションおよび正規化が機能すること"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)

        # 1. 辞書でない不正フォーマット (422 Unprocessable Entity)
        resp = test_client.post("/soul/record", json="not a dict")
        assert resp.status_code == 422

        # 2. 正常系で値が非標準型（自動キャストと補正）
        resp = test_client.post(
            "/soul/record",
            json={
                "summary": 12345,         # 文字列キャストされるべき
                "insight": None,          # 空文字列になるべき
                "stat_changes": "XP +50", # 単一要素リストになるべき
                "philosophy_evolved": 1   # bool化されるべき
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recorded"
        entry = data["entry"]
        assert entry["summary"] == "12345"
        assert entry["insight"] == ""
        assert entry["stat_changes"] == ["XP +50"]
        assert entry["philosophy_evolved"] is True

    def test_soul_endpoints_robustness_with_bad_types(self, test_client, mock_soul_paths, monkeypatch):
        """JSONデータが不正な型（リスト想定箇所に文字列や辞書など）を保持していても、例外で落ちずに安全に応答すること"""
        monkeypatch.setattr(soul_router, "HAS_ADK", False)
        test_evo_log, test_constitution = mock_soul_paths

        # entries や decision_insights がリストではなく辞書や文字列などの場合
        bad_log = {
            "entries": "not a list",
            "decision_insights": {"key": "not a list"},
            "philosophies": 9999
        }
        test_evo_log.write_text(json.dumps(bad_log, ensure_ascii=False), encoding="utf-8")

        # ダッシュボード
        resp = test_client.get("/soul/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["philosophy"]["total_philosophies"] == 0
        assert data["statistics"]["total_sessions"] == 0
        assert data["rank"]["xp"] == 0

        # chronicle
        resp = test_client.get("/soul/chronicle")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        # _calculate_xp に不正な要素を混ぜる
        from routers.soul_router import _calculate_xp
        bad_entries = ["not a dict", {"summary": "valid"}, None]
        xp = _calculate_xp(bad_entries)
        assert xp == 50 # 有効なのは真ん中の1件だけ(基本50XP)

