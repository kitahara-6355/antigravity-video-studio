"""
Sprint 4.6.2: B分類カバレッジ改善テスト
decision_logger / safe_io / routers/websocket (32テスト)

設計書: sprint_462_b_class_design.md (conv_8a2ec2b6)
"""
import pytest
import json
import sys
import os
import time
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from dataclasses import asdict


# ============================================================
# Helper: テスト用DecisionLoggerインスタンス生成
# ============================================================
def _make_decision_logger(tmp_path):
    """テスト用DecisionLoggerインスタンスを生成(ファイルI/O安全)"""
    from decision_logger import DecisionLogger
    with patch.object(DecisionLogger, "__init__", lambda self: None):
        dl = DecisionLogger()
        dl.log_dir = tmp_path / "branding"
        dl.log_dir.mkdir(parents=True, exist_ok=True)
        dl.log_file = dl.log_dir / "decision_log.json"
        dl.decisions = []
        return dl


def _make_decision(decision_id="d1", decision="approve", reason="good",
                   tags=None, learned=False, target_type="screenshot",
                   target_description="test desc"):
    """テスト用Decisionオブジェクト生成"""
    from decision_logger import Decision
    return Decision(
        decision_id=decision_id,
        timestamp=time.time(),
        iso_time="2026-01-01T00:00:00",
        target_type=target_type,
        target_path="/test/path",
        target_description=target_description,
        decision=decision,
        reason=reason,
        scene_info={},
        mood_settings={},
        tags=tags or [],
        learned=learned,
    )


# ============================================================
# TestDecisionLoggerSync (DL-01 ~ DL-12)
# ============================================================
class TestDecisionLoggerSync:
    """decision_logger.py sync_to_soul_narrative カバレッジ改善"""

    # DL-01: 全decisions.learned=True → synced=0
    def test_sync_soul_no_unsynced(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        dl.decisions = [_make_decision(learned=True)]
        result = dl.sync_to_soul_narrative()
        assert result["synced"] == 0
        assert result["new_insights"] == []

    # DL-02: evo_log不在 → 新規作成
    def test_sync_soul_evolution_log_new(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        dl.decisions = [_make_decision(learned=False)]
        evo_path = dl.log_dir / "evolution_log.json"
        assert not evo_path.exists()
        result = dl.sync_to_soul_narrative()
        assert result["synced"] == 1
        assert evo_path.exists()
        data = json.loads(evo_path.read_text(encoding="utf-8"))
        assert "decision_insights" in data

    # DL-03: 却下decisions → preference型insight生成
    def test_sync_soul_rejection_insight(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        dl.decisions = [
            _make_decision(decision_id="r1", decision="reject",
                           reason="色が暗すぎる", learned=False),
        ]
        result = dl.sync_to_soul_narrative()
        assert result["synced"] == 1
        pref_insights = [i for i in result["new_insights"]
                         if i["type"] == "preference"]
        assert len(pref_insights) == 1
        assert "色が暗すぎる" in pref_insights[0]["content"]

    # DL-04: 承認decisions+tags → style_preference型insight
    def test_sync_soul_approval_style_insight(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        dl.decisions = [
            _make_decision(decision_id="a1", decision="approve",
                           tags=["明るい色調", "テンポ速い"], learned=False),
            _make_decision(decision_id="a2", decision="approve",
                           tags=["明るい色調"], learned=False),
        ]
        result = dl.sync_to_soul_narrative()
        style_insights = [i for i in result["new_insights"]
                          if i["type"] == "style_preference"]
        assert len(style_insights) == 1
        assert "明るい色調" in style_insights[0]["content"]

    # DL-05: evo_log.entries追加 + decision_insights追加
    def test_sync_soul_evolution_log_append(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        # 既存evo_logを作成
        evo_path = dl.log_dir / "evolution_log.json"
        existing = {"entries": [{"type": "old"}], "philosophies": [],
                    "decision_insights": [{"type": "old_insight"}]}
        evo_path.write_text(json.dumps(existing), encoding="utf-8")

        dl.decisions = [_make_decision(decision_id="n1", learned=False)]
        result = dl.sync_to_soul_narrative()
        data = json.loads(evo_path.read_text(encoding="utf-8"))
        # 既存entriesに追加されている
        assert len(data["entries"]) == 2
        assert data["entries"][0]["type"] == "old"
        assert data["entries"][1]["type"] == "decision_sync"

    # DL-06: sync後に全unsynced.learned=True
    def test_sync_soul_marks_learned(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        d1 = _make_decision(decision_id="m1", learned=False)
        d2 = _make_decision(decision_id="m2", learned=False)
        dl.decisions = [d1, d2]
        dl.sync_to_soul_narrative()
        assert d1.learned is True
        assert d2.learned is True

    # DL-07: wagamama_id:タグ → resolve_story呼出
    def test_sync_soul_wagamama_integration(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        dl.decisions = [
            _make_decision(decision_id="w1", decision="approve",
                           tags=["wagamama_id:W001"], learned=False),
        ]
        mock_wm = MagicMock()
        mock_wm.resolve_story = MagicMock()
        mock_module = MagicMock()
        mock_module.wagamama_manager = mock_wm
        with patch.dict("sys.modules", {"wagamama_manager": mock_module}):
            dl.sync_to_soul_narrative()
            mock_wm.resolve_story.assert_called_once()
            call_kwargs = mock_wm.resolve_story.call_args
            assert call_kwargs[1]["wagamama_id"] == "W001"

    # DL-08: wagamama_manager ImportError → 正常続行
    def test_sync_soul_wagamama_import_error(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        dl.decisions = [
            _make_decision(decision_id="w2", decision="approve",
                           tags=["wagamama_id:W002"], learned=False),
        ]
        # wagamama_managerがsys.modulesにない状態でImportErrorが発生
        with patch.dict("sys.modules", {"wagamama_manager": None}):
            # ImportError発生しても正常続行
            result = dl.sync_to_soul_narrative()
            assert result["synced"] == 1

    # DL-09: 却下あり → "こだわり"テキスト含む
    def test_generate_insight_summary_rejections(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        decisions = [
            _make_decision(decision="reject", reason="テンポが遅すぎる"),
        ]
        result = dl._generate_insight_summary(decisions)
        assert "こだわり" in result
        assert "テンポが遅すぎる" in result

    # DL-10: 承認あり → "好み"テキスト含む
    def test_generate_insight_summary_approvals(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        decisions = [
            _make_decision(decision="approve", reason="いい感じ"),
        ]
        result = dl._generate_insight_summary(decisions)
        assert "好み" in result

    # DL-11: 空リスト → デフォルトメッセージ
    def test_generate_insight_summary_empty(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        result = dl._generate_insight_summary([])
        assert "新しい意思決定が記録されました" in result

    # DL-12: sync_to_evolution_log() → sync_to_soul_narrativeへ委譲
    def test_sync_to_evolution_log_alias(self, tmp_path):
        dl = _make_decision_logger(tmp_path)
        dl.decisions = [_make_decision(learned=False)]
        with patch.object(dl, "sync_to_soul_narrative",
                          return_value={"synced": 99}) as mock_sync:
            result = dl.sync_to_evolution_log()
            mock_sync.assert_called_once()
            assert result["synced"] == 99


# ============================================================
# TestSafeJsonStore (SI-01 ~ SI-10)
# ============================================================
class TestSafeJsonStore:
    """safe_io.py SafeJsonStore カバレッジ改善"""

    # SI-01: 初期化
    def test_init_default(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "test.json"
        default = {"key": "val"}
        store = SafeJsonStore(p, default=default)
        assert store._path == p
        assert store._default == default
        assert store._lock is not None

    # SI-02: pathプロパティ
    def test_path_property(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "test.json"
        store = SafeJsonStore(p)
        assert store.path == p

    # SI-03: ファイル不在 → default返却
    def test_load_nonexistent(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "missing.json"
        default = {"empty": True}
        store = SafeJsonStore(p, default=default)
        result = store.load()
        assert result == {"empty": True}
        # コピーであることを確認(元データ汚染防止)
        result["extra"] = 1
        assert "extra" not in store._default

    # SI-04: 正常JSON → dict返却
    def test_load_valid_json(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "data.json"
        data = {"series": {"s1": {"name": "test"}}}
        p.write_text(json.dumps(data), encoding="utf-8")
        store = SafeJsonStore(p)
        result = store.load()
        assert result == data

    # SI-05: 不正JSON → default返却 + エラーログ
    def test_load_corrupt_json(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "corrupt.json"
        p.write_text("{invalid json!!}", encoding="utf-8")
        default = {"fallback": True}
        store = SafeJsonStore(p, default=default)
        result = store.load()
        assert result == {"fallback": True}

    # SI-06: save → アトミック書き込み + ファイル生成
    def test_save_creates_file(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "output.json"
        store = SafeJsonStore(p)
        data = {"saved": True, "count": 42}
        store.save(data)
        assert p.exists()
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded == data

    # SI-07: 書き込み失敗 → tempfile削除 + 例外re-raise
    def test_save_atomic_error_cleanup(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "fail.json"
        store = SafeJsonStore(p)
        # json.dumpで失敗するデータ(循環参照相当)
        with patch("safe_io.json.dump", side_effect=TypeError("not serializable")):
            with pytest.raises(TypeError, match="not serializable"):
                store.save({"data": "test"})
        # tempfileが残っていないことを確認
        tmp_files = list(tmp_path.glob(".*_*.tmp"))
        assert len(tmp_files) == 0

    # SI-08: update - updater_fnがdictを返す
    def test_update_with_return(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "update.json"
        p.write_text(json.dumps({"v": 1}), encoding="utf-8")
        store = SafeJsonStore(p)
        result = store.update(lambda data: {"v": data["v"] + 1, "new": True})
        assert result["v"] == 2
        assert result["new"] is True
        # ファイルにも反映
        saved = json.loads(p.read_text(encoding="utf-8"))
        assert saved["v"] == 2

    # SI-09: update - updater_fnがNone返す(in-place変更)
    def test_update_in_place(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "inplace.json"
        p.write_text(json.dumps({"items": []}), encoding="utf-8")
        store = SafeJsonStore(p)

        def mutator(data):
            data["items"].append("added")
            # Noneを返す(暗黙return)

        result = store.update(mutator)
        assert result["items"] == ["added"]
        saved = json.loads(p.read_text(encoding="utf-8"))
        assert saved["items"] == ["added"]

    # SI-10: _load_unsafe / _save_unsafe 単体呼出
    def test_load_unsafe_and_save_unsafe(self, tmp_path):
        from safe_io import SafeJsonStore
        p = tmp_path / "unsafe.json"
        store = SafeJsonStore(p, default={"init": True})

        # _load_unsafe: ファイル不在 → default
        result = store._load_unsafe()
        assert result == {"init": True}

        # _save_unsafe: 書き込み
        store._save_unsafe({"saved_unsafe": True})
        assert p.exists()
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded["saved_unsafe"] is True

        # _load_unsafe: ファイル存在 → データ返却
        result2 = store._load_unsafe()
        assert result2["saved_unsafe"] is True

        # _load_unsafe: 不正JSON → default
        p.write_text("{{bad}}", encoding="utf-8")
        result3 = store._load_unsafe()
        assert result3 == {"init": True}


# ============================================================
# TestWebSocketRouter (WS-01 ~ WS-10)
# ============================================================
class TestWebSocketRouter:
    """routers/websocket.py カバレッジ改善"""

    # WS-01: model_registry ImportError → fallback関数
    def test_model_registry_import_fallback(self):
        import importlib.util
        # routers/__init__.pyの連鎖importを回避するため、直接ファイルロード
        ws_path = Path(__file__).resolve().parent.parent.parent / "routers" / "websocket.py"
        saved_mr = sys.modules.pop("model_registry", None)
        sys.modules["model_registry"] = None
        try:
            spec = importlib.util.spec_from_file_location(
                "_test_ws_fallback", str(ws_path)
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
            # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
            from model_policy import resolve
            assert mod.get_model("any_task") == resolve("any_task").model
            assert mod.get_model("live_api") == resolve("live_api").model
            assert not mod.get_model("any_task").startswith("gemini-2.5")
        finally:
            if saved_mr is not None:
                sys.modules["model_registry"] = saved_mr
            else:
                sys.modules.pop("model_registry", None)

    # WS-02: connect() → active_connections+1, accept()呼出
    @pytest.mark.asyncio
    async def test_connection_manager_connect(self):
        from routers.websocket import ConnectionManager
        cm = ConnectionManager()
        mock_ws = AsyncMock()
        await cm.connect(mock_ws)
        assert mock_ws in cm.active_connections
        assert len(cm.active_connections) == 1
        mock_ws.accept.assert_awaited_once()

    # WS-03: disconnect() → active_connections-1
    @pytest.mark.asyncio
    async def test_connection_manager_disconnect(self):
        from routers.websocket import ConnectionManager
        cm = ConnectionManager()
        mock_ws = AsyncMock()
        cm.active_connections.append(mock_ws)
        cm.disconnect(mock_ws)
        assert mock_ws not in cm.active_connections

    # WS-04: 未登録ws → removeされずエラーなし
    def test_connection_manager_disconnect_nonmember(self):
        from routers.websocket import ConnectionManager
        cm = ConnectionManager()
        mock_ws = MagicMock()
        # 未登録wsのdisconnect → エラーなし
        cm.disconnect(mock_ws)
        assert len(cm.active_connections) == 0

    # WS-05: broadcast() → 全接続にsend_json
    @pytest.mark.asyncio
    async def test_connection_manager_broadcast(self):
        from routers.websocket import ConnectionManager
        cm = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        cm.active_connections = [ws1, ws2]
        msg = {"type": "progress", "value": 50}
        await cm.broadcast(msg)
        ws1.send_json.assert_awaited_once_with(msg)
        ws2.send_json.assert_awaited_once_with(msg)

    # WS-06: send_json例外 → error log + 他接続に影響なし
    @pytest.mark.asyncio
    async def test_connection_manager_broadcast_error(self):
        from routers.websocket import ConnectionManager
        cm = ConnectionManager()
        ws_fail = AsyncMock()
        ws_fail.send_json.side_effect = Exception("connection lost")
        ws_ok = AsyncMock()
        cm.active_connections = [ws_fail, ws_ok]
        msg = {"type": "update"}
        await cm.broadcast(msg)
        # 失敗した接続のsend_jsonは呼ばれた
        ws_fail.send_json.assert_awaited_once_with(msg)
        # 他の接続は影響なく送信成功
        ws_ok.send_json.assert_awaited_once_with(msg)

    # WS-07: progress endpoint echo
    @pytest.mark.asyncio
    async def test_progress_endpoint_echo(self):
        from routers.websocket import ConnectionManager, WebSocketDisconnect

        cm = ConnectionManager()
        mock_ws = AsyncMock()
        # receive_text: 1回目はテキスト返却、2回目はWebSocketDisconnect
        mock_ws.receive_text = AsyncMock(
            side_effect=["hello", WebSocketDisconnect()]
        )

        # websocket_progress_endpointを直接テスト
        from routers.websocket import websocket_progress_endpoint
        # managerをパッチ
        with patch("routers.websocket.manager", cm):
            await websocket_progress_endpoint(mock_ws)

        # accept + エコー + disconnect
        mock_ws.accept.assert_awaited_once()
        mock_ws.send_json.assert_awaited_once_with({
            "type": "echo",
            "message": "hello",
        })

    # WS-08: broadcast_progress() → manager.broadcast呼出
    @pytest.mark.asyncio
    async def test_broadcast_progress_function(self):
        from routers.websocket import broadcast_progress
        mock_manager = AsyncMock()
        with patch("routers.websocket.manager", mock_manager):
            data = {"type": "progress", "percent": 75}
            await broadcast_progress(data)
            mock_manager.broadcast.assert_awaited_once_with(data)

    # WS-09: live_endpoint gemini ImportError → close(1011)
    @pytest.mark.asyncio
    async def test_live_endpoint_gemini_import_error(self):
        mock_ws = AsyncMock()
        # google.genaiのインポートが失敗するケース
        with patch.dict("sys.modules", {"google": None, "google.genai": None}):
            from routers.websocket import websocket_live_endpoint
            await websocket_live_endpoint(mock_ws)
        # accept呼出後、ImportErrorでclose
        mock_ws.accept.assert_awaited_once()
        mock_ws.close.assert_awaited_once()
        close_kwargs = mock_ws.close.call_args
        assert close_kwargs[1]["code"] == 1011

    # WS-10: live_endpoint WebSocketDisconnect → ログ出力のみ
    @pytest.mark.asyncio
    async def test_live_endpoint_websocket_disconnect(self):
        from fastapi import WebSocketDisconnect
        mock_ws = AsyncMock()

        # google.genaiインポート成功、但しconnectでWebSocketDisconnect
        mock_genai = MagicMock()
        mock_client = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(
            side_effect=WebSocketDisconnect()
        )
        mock_session.__aexit__ = AsyncMock()
        mock_client.aio.live.connect.return_value = mock_session
        mock_factory = MagicMock(return_value=mock_client)

        with patch.dict("sys.modules", {
            "google": MagicMock(),
            "google.genai": mock_genai,
            "gemini_client_factory": MagicMock(
                get_gemini_client=mock_factory
            ),
        }):
            import importlib
            import routers.websocket as ws_mod
            importlib.reload(ws_mod)
            await ws_mod.websocket_live_endpoint(mock_ws)

        # WebSocketDisconnect → closeは呼ばれない(正常切断)
        mock_ws.accept.assert_awaited_once()
        mock_ws.close.assert_not_awaited()

        # モジュール復元
        import importlib
        importlib.reload(ws_mod)
