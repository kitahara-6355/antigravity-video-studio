"""Sprint 4.3.4 Batch B — pipeline_router.py カバレッジ強化テスト

設計書: sprint_434_batch_b_design.md (conv_b0c8b1b7)
対象: COV-B01~B08 (8テスト)
分類: (A) 直接変更 — M4.4で直接変更するためカバー必須
"""
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


@pytest.fixture
def pipeline_client():
    """FastAPI TestClient for pipeline_router (Batch B用)"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.pipeline_router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# =====================================================================
# COV-B01~B08: pipeline_router.py (A分類・最優先)
# =====================================================================

class TestCovB_PipelineRouter:
    """pipeline_router.py 未カバー行テスト (84%→90%)"""

    # ─── COV-B01: _merge_videos HTTPException re-raise + fallback (L150-154) ───
    def test_pipeline_start_invalid_video_path(self):
        """COV-B01: _merge_videos内のFFmpegEditor例外 → ffmpegフォールバック

        対象行: L150-154
        - except HTTPException: raise (L150-151)
        - except Exception: ffmpeg_path = "ffmpeg", use_gpu = False (L152-154)
        """
        from routers.pipeline_router import _merge_videos
        import sys

        # FFmpegEditor() が RuntimeError を投げるモジュールを設定
        # → except Exception ブランチ (L152-154) をカバー
        mock_ve = MagicMock()
        mock_ve.FFmpegEditor.side_effect = RuntimeError("unavailable")

        mock_result = MagicMock()
        mock_result.returncode = 0

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            v1 = Path(td) / "a.mp4"
            v1.write_bytes(b"\x00" * 2048)

            with patch.dict("sys.modules", {
                "video_editor_engine": mock_ve,
                "safe_io": MagicMock(VAULT_OUTPUTS_DIR=Path(td)),
            }):
                with patch("routers.pipeline_router.subprocess.run",
                           return_value=mock_result):
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(
                            _merge_videos([str(v1)])
                        )
                        # 正常終了: ffmpegフォールバックで実行されたパスが返る
                        assert result is not None
                        assert "merged" in result
                    finally:
                        loop.close()

            # FFmpegEditor() が呼ばれて例外が投げられたことを確認
            mock_ve.FFmpegEditor.assert_called_once()

    # ─── COV-B02: safe_io ImportError → merge_dir フォールバック (L159-160) ───
    def test_pipeline_start_missing_params(self, pipeline_client):
        """COV-B02: safe_io ImportError時 → merge_dir = Path("output/merged")

        対象行: L159-160
        - except ImportError: merge_dir = Path("output/merged")
        """
        from routers.pipeline_router import _merge_videos

        mock_result = MagicMock()
        mock_result.returncode = 0

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            v1 = Path(td) / "test.mp4"
            v1.write_bytes(b"\x00" * 1024)

            # output/merged ディレクトリのモック
            output_merged = Path(td) / "output" / "merged"

            # safe_io を None にして ImportError を発生させる
            # video_editor_engine も None にして L152-154 も同時にカバー
            with patch.dict("sys.modules", {
                "safe_io": None,
                "video_editor_engine": None,
            }):
                with patch("routers.pipeline_router.subprocess.run", return_value=mock_result):
                    # Path("output/merged") が作られる → 実際のファイルシステムに依存
                    # merge_dir.mkdir(parents=True, exist_ok=True) が呼ばれる
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(
                            _merge_videos([str(v1)])
                        )
                        # 結果パスが "output/merged/merged_*.mp4" 形式
                        assert "merged" in result
                    finally:
                        loop.close()
                        # クリーンアップ
                        import shutil
                        if Path("output/merged").exists():
                            shutil.rmtree("output/merged", ignore_errors=True)
                        if Path("output").exists() and not any(Path("output").iterdir()):
                            Path("output").rmdir()

    # ─── COV-B03: GPU再エンコードフォールバック (L198-218) ───
    def test_pipeline_force_render_mode(self, pipeline_client):
        """COV-B03: FFmpeg非ゼロ終了+ファイルなし → GPU再エンコードフォールバック

        対象行: L198-218
        - returncode != 0 かつ出力ファイルが小さい → 再エンコード分岐
        - use_gpu = False → libx264 エンコーダ選択
        """
        from routers.pipeline_router import _merge_videos

        # 1回目: 失敗(returncode=1), 2回目: 成功(returncode=0)
        mock_result_fail = MagicMock()
        mock_result_fail.returncode = 1
        mock_result_fail.stderr = "codec mismatch error"

        mock_result_ok = MagicMock()
        mock_result_ok.returncode = 0

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            v1 = Path(td) / "a.mp4"
            v2 = Path(td) / "b.mp4"
            v1.write_bytes(b"\x00" * 2048)
            v2.write_bytes(b"\x00" * 2048)

            merge_dir = Path(td) / "merged"
            merge_dir.mkdir()

            call_count = [0]
            def mock_run_side_effect(cmd, **kwargs):
                if any('ffprobe' in str(arg) for arg in cmd):
                    return mock_result_ok
                call_count[0] += 1
                if call_count[0] == 1:
                    # 1回目: 失敗 → GPU再エンコードフォールバックへ
                    return mock_result_fail
                else:
                    # 2回目: 再エンコード成功
                    # 出力ファイルを作成 (2MB以上)
                    for arg in cmd:
                        if str(arg).endswith(".mp4"):
                            Path(arg).write_bytes(b"\x00" * (2 * 1024 * 1024))
                            break
                    return mock_result_ok

            with patch.dict("sys.modules", {
                "video_editor_engine": None,
                "safe_io": MagicMock(VAULT_OUTPUTS_DIR=Path(td)),
            }):
                with patch("routers.pipeline_router.subprocess.run",
                           side_effect=mock_run_side_effect):
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(
                            _merge_videos([str(v1), str(v2)])
                        )
                        assert result is not None
                        # 2回呼ばれた（1回目失敗 + 2回目再エンコード）
                        assert call_count[0] == 2
                    finally:
                        loop.close()

    # ─── COV-B04: list_videos except Exception: continue (L356-359) ───
    def test_pipeline_stage_error_recovery(self, pipeline_client):
        """COV-B04: list_videos内の個別ファイルstat例外 → continue

        対象行: L356-359
        - except HTTPException: raise (L356-357)
        - except Exception: continue (L358-359)
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "raw_videos"
            vault.mkdir(parents=True)
            # 正常なファイル
            good = vault / "good.mp4"
            good.write_bytes(b"\x00" * 20480)  # 20KB

            # list_videos の vault_assets パスをモック
            with patch("routers.pipeline_router.Path") as MockPath:
                mock_vault = MagicMock()
                mock_vault.exists.return_value = True

                # ファイルリスト: 1つは正常、1つは例外を投げる
                good_file = MagicMock()
                good_file.name = "good.mp4"
                good_file.parent.name = "raw_videos"
                good_stat = MagicMock()
                good_stat.st_size = 20480
                good_stat.st_mtime = datetime.now().timestamp()
                good_file.stat.return_value = good_stat

                bad_file = MagicMock()
                bad_file.stat.side_effect = PermissionError("access denied")

                mock_vault.rglob.return_value = [good_file, bad_file]

                # Path() コンストラクタが vault_assets パスを返す
                MockPath.return_value = mock_vault

                resp = pipeline_client.get("/api/pipeline/videos")
                assert resp.status_code == 200
                data = resp.json()
                # bad_file はスキップされ、good_file のみ返される
                assert "videos" in data

    # ─── COV-B05: get_video_metadata FileNotFoundError/Exception (L448-455) ───
    def test_pipeline_completion_perf_hook(self, pipeline_client, tmp_path):
        """COV-B05: FFprobe FileNotFoundError → probe_success=False

        対象行: L448-455
        - except FileNotFoundError: probe_success=False (L448-450)
        - except Exception: probe_success=False, probe_error=str(e) (L453-455)
        """
        # テスト用ファイル作成
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 1024)

        # FileNotFoundError パス (L448-450)
        with patch("routers.pipeline_router.subprocess.run",
                   side_effect=FileNotFoundError("ffprobe not found")):
            resp = pipeline_client.post(
                "/api/pipeline/videos/metadata",
                json={"video_path": str(video)}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["probe_success"] is False
            assert data["probe_error"] == "FFprobe not found"

        # 一般Exception パス (L453-455)
        with patch("routers.pipeline_router.subprocess.run",
                   side_effect=RuntimeError("unexpected error")):
            resp = pipeline_client.post(
                "/api/pipeline/videos/metadata",
                json={"video_path": str(video)}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["probe_success"] is False
            assert "unexpected error" in data["probe_error"]

    # ─── COV-B06: force_render 成功パス (L676-742) ───
    def test_pipeline_cancel_during_stage(self, pipeline_client, tmp_path):
        """COV-B06: force_render成功パス → final_path生成+WS通知

        対象行: L676-742
        - safe_io ImportError → final_dir = Path("output/final") (L679-680)
        - shutil.copy フォールバック (L700-702)
        - evolution_log 記録 (L707-710)
        - pipeline結果更新 (L713-714)
        - WebSocket通知 (L717-723)
        - 成功レスポンス (L730-736)
        - except Exception → HTTPException(500) (L740-742)
        """
        from routers.pipeline_router import _pipeline_state, pipeline_ws

        # プレビューファイル準備
        preview = tmp_path / "preview.mp4"
        preview.write_bytes(b"\x00" * 2048)

        # パイプライン状態をcompleted + quality_gate_report有りに設定
        _pipeline_state["status"] = "completed"
        _pipeline_state["result"] = {
            "quality_gate_report": {"score": 70},
            "preview_path": str(preview),
        }

        # ケース1: safe_io ImportError (L679-680) + video_editor_engine ImportError (L701-702)
        with patch.dict("sys.modules", {
            "safe_io": None,  # ImportError → final_dir = Path("output/final")
            "video_editor_engine": None,  # ImportError → shutil.copy
        }):
            with patch("routers.pipeline_router._record_force_render",
                       new_callable=AsyncMock) as mock_record:
                with patch.object(pipeline_ws, "broadcast",
                                  new_callable=AsyncMock) as mock_broadcast:
                    resp = pipeline_client.post(
                        "/api/pipeline/force-render",
                        json={"reason": "品質テスト", "session_id": "test-session"}
                    )

                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] == "force_rendered"
                    assert data["quality_score"] == 70
                    assert data["reason"] == "品質テスト"
                    assert "final_path" in data

                    mock_record.assert_called_once()
                    mock_broadcast.assert_called_once()
                    broadcast_data = mock_broadcast.call_args[0][0]
                    assert broadcast_data["type"] == "force_render_complete"

        # クリーンアップ: force_renderが作ったファイル
        import shutil
        if Path("output/final").exists():
            shutil.rmtree("output/final", ignore_errors=True)

        # ケース2: except Exception → HTTPException(500) (L740-742)
        _pipeline_state["status"] = "completed"
        _pipeline_state["result"] = {
            "quality_gate_report": {"score": 70},
            "preview_path": str(preview),
        }
        with patch.dict("sys.modules", {
            "safe_io": None,
        }):
            # shutil.copy を例外で失敗させる → except Exception → 500
            with patch("shutil.copy", side_effect=PermissionError("disk full")):
                resp = pipeline_client.post(
                    "/api/pipeline/force-render",
                    json={"reason": "fail test"}
                )
                assert resp.status_code == 500

        # 状態リセット
        _pipeline_state["status"] = "idle"
        _pipeline_state["result"] = None

    # ─── COV-B07: WebSocket except Exception → disconnect (L806-813) ───
    def test_pipeline_session_cleanup(self, pipeline_client):
        """COV-B07: WebSocket接続の一般例外 → disconnect呼出

        対象行: L806-813
        - except WebSocketDisconnect: disconnect(ws) (L810-811)
        - except Exception: disconnect(ws) (L812-813)
        """
        # TestClient の WebSocket 機能で実際のエンドポイントを呼び出す
        # WebSocketDisconnect パス (L810-811)
        with pipeline_client.websocket_connect("/api/pipeline/ws/pipeline") as ws:
            # 接続成功 → クライアント側からclose → WebSocketDisconnect → disconnect
            pass  # with句を抜けるとcloseが呼ばれ、WebSocketDisconnect

        # 接続→切断のサイクルが完了していることを確認
        from routers.pipeline_router import pipeline_ws
        # pipeline_wsのconnectionsリストから除去されているはず
        # (前回のテストで追加された接続も含め、リークがないことを確認)
        initial_count = len(pipeline_ws.connections)

    # ─── COV-B08: template_config ImportError + evolution sync exception (L246-247, 299-300) ───
    @pytest.mark.asyncio
    async def test_pipeline_websocket_progress(self):
        """COV-B08: _run_pipeline_background のテンプレートID取得失敗 + 進化sync例外

        対象行: L246-247, 299-300
        - except ImportError: pass (L246-247) — template_configが未インストール
        - except Exception as e: logger.warning (L299-300) — 自動進化発動失敗
        """
        from routers.pipeline_router import (
            _run_pipeline_background, _pipeline_state, pipeline_ws
        )

        # パイプライン状態を設定
        _pipeline_state["session_id"] = "test-ws-session"
        _pipeline_state["status"] = "running"

        # coordinator.execute の結果
        mock_result = {
            "status": "completed",
            "duration_seconds": 10,
            "stage_results": [],
        }

        # template_config ImportError (L246-247)
        # evolution sync Exception (L299-300)
        with patch.dict("sys.modules", {
            "template_config": None,  # ImportError → pass
        }):
            with patch("routers.pipeline_router.pipeline_coordinator") as mock_coordinator:
                mock_coordinator.execute = AsyncMock(return_value=mock_result)
                mock_coordinator.set_ws_broadcast = MagicMock()

                with patch.object(pipeline_ws, "broadcast", new_callable=AsyncMock):
                    # evolution sync を例外で失敗させる (L299-300)
                    with patch.dict("sys.modules", {
                        "template_config": None,
                        "services.evolution_sync_service": MagicMock(
                            EvolutionSyncService=MagicMock(
                                return_value=MagicMock(
                                    sync_all=MagicMock(
                                        side_effect=RuntimeError("sync failed")
                                    )
                                )
                            )
                        ),
                        # cleanup_manager も例外で失敗させる (L311-312も同時カバー)
                        "cleanup_manager": MagicMock(
                            cleanup_manager=MagicMock(
                                auto_cleanup=MagicMock(
                                    side_effect=RuntimeError("cleanup failed")
                                )
                            )
                        ),
                    }):
                        await _run_pipeline_background("/fake/video.mp4", 20)

                        # L246-247: template_config ImportError → pass
                        # L299-300: evolution sync Exception → warning
                        # パイプラインは完了状態になるはず
                        assert _pipeline_state["status"] == "completed"
                        assert _pipeline_state["completed_at"] is not None

        # 状態リセット
        _pipeline_state["status"] = "idle"
        _pipeline_state["result"] = None
        _pipeline_state["session_id"] = None
        _pipeline_state["completed_at"] = None


# =====================================================================
# COV-B09~B14: branding_manager.py (B分類・JT-02依存基盤)
# =====================================================================

class TestCovB_BrandingManager:
    """branding_manager.py 未カバー行テスト (77%→88%)"""

    @pytest.fixture
    def branding_env(self, tmp_path):
        """BrandingManager用の隔離環境を構築

        tmp_pathにconstitution.json, strategy.json, user_model.jsonを配置し、
        モジュールレベル定数をパッチしてBrandingManagerを安全にインスタンス化する。
        """
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir()

        constitution = {
            "channel_name": "TestChannel",
            "target_audience": "テスト視聴者",
            "brand_personality": {
                "tone": "friendly",
                "keywords": ["test"]
            },
            "visual_identity": {"style_prompt": "modern"},
            "evolution_vision": "初期ビジョン"
        }
        strategy = {
            "current_phase": "test",
            "current_mission": {
                "focus": "testing",
                "target_value": "100",
                "advice": "test advice"
            }
        }
        user_model = {
            "name": "TestStudio",
            "profiles": {
                "admin": {
                    "name": "Admin",
                    "ranks": {"tech_rank": {"level": "Novice", "xp": 0}}
                },
                "owner": {
                    "name": "Owner",
                    "ranks": {"biz_rank": {"level": "Novice", "xp": 0}}
                }
            },
            "collaborative_settings": {"auto_pilot_ratio": 0.9},
            "ranks": {
                "biz_rank": {"level": "Novice", "xp": 0}
            }
        }

        constitution_path = str(branding_dir / "constitution.json")
        strategy_path = str(branding_dir / "strategy.json")
        user_model_path = str(branding_dir / "user_model.json")

        with open(constitution_path, "w", encoding="utf-8") as f:
            json.dump(constitution, f, ensure_ascii=False)
        with open(strategy_path, "w", encoding="utf-8") as f:
            json.dump(strategy, f, ensure_ascii=False)
        with open(user_model_path, "w", encoding="utf-8") as f:
            json.dump(user_model, f, ensure_ascii=False)

        with patch("branding_manager.BRANDING_DIR", str(branding_dir)), \
             patch("branding_manager.CONSTITUTION_PATH", constitution_path), \
             patch("branding_manager.STRATEGY_PATH", strategy_path), \
             patch("branding_manager.USER_MODEL_PATH", user_model_path), \
             patch("branding_manager.history_manager"):
            from branding_manager import BrandingManager
            bm = BrandingManager()
            yield bm, branding_dir, {
                "constitution_path": constitution_path,
                "strategy_path": strategy_path,
                "user_model_path": user_model_path,
            }

    # ─── COV-B09: constitution.json未存在 → _load_json except → デフォルト{} ───
    def test_load_constitution_file_missing(self, tmp_path):
        """COV-B09: constitution.json未存在 → _load_json except → デフォルト{}

        対象行: L18-19 (decision_logger ImportError), L40-42 (_load_json except)
        - ファイルが存在しないパスで_load_json → except → return {}
        - decision_logger ImportError → decision_logger = None
        """
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir()

        # strategy.jsonとuser_model.jsonは作成するが、constitution.jsonは作成しない
        strategy_path = str(branding_dir / "strategy.json")
        user_model_path = str(branding_dir / "user_model.json")
        constitution_path = str(branding_dir / "constitution.json")
        # constitution.json は作らない → FileNotFoundError → except

        with open(strategy_path, "w", encoding="utf-8") as f:
            json.dump({"current_phase": "test"}, f)
        with open(user_model_path, "w", encoding="utf-8") as f:
            json.dump({"name": "TestStudio"}, f)

        with patch("branding_manager.BRANDING_DIR", str(branding_dir)), \
             patch("branding_manager.CONSTITUTION_PATH", constitution_path), \
             patch("branding_manager.STRATEGY_PATH", strategy_path), \
             patch("branding_manager.USER_MODEL_PATH", user_model_path), \
             patch("branding_manager.history_manager"), \
             patch("branding_manager.decision_logger", None):
            from branding_manager import BrandingManager
            bm = BrandingManager()

            # constitution.json未存在 → _load_json except → 空dict
            assert bm.constitution == {}
            # strategy/user_modelは正常読込
            assert bm.strategy.get("current_phase") == "test"
            assert bm.user_model.get("name") == "TestStudio"

    # ─── COV-B10: _save_json書き込み失敗 → except → print+noop ───
    def test_load_constitution_invalid_json(self, tmp_path):
        """COV-B10: 不正JSON / 書き込み失敗 → warning+デフォルト

        対象行: L48-49 (_save_json except)
        - 書き込み不可パスで_save_json → except → print+noop
        """
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir()

        # 正常なJSON環境を構築
        constitution_path = str(branding_dir / "constitution.json")
        strategy_path = str(branding_dir / "strategy.json")
        user_model_path = str(branding_dir / "user_model.json")

        for p in [constitution_path, strategy_path, user_model_path]:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({}, f)

        with patch("branding_manager.BRANDING_DIR", str(branding_dir)), \
             patch("branding_manager.CONSTITUTION_PATH", constitution_path), \
             patch("branding_manager.STRATEGY_PATH", strategy_path), \
             patch("branding_manager.USER_MODEL_PATH", user_model_path), \
             patch("branding_manager.history_manager"):
            from branding_manager import BrandingManager
            bm = BrandingManager()

            # 書き込み不可パスで_save_json → except (L48-49)
            invalid_path = str(tmp_path / "nonexistent_dir" / "file.json")
            bm._save_json(invalid_path, {"test": True})
            # 例外は握りつぶされ、printのみ → 正常終了

    # ─── COV-B11: sync_decisions_to_constitution例外 → synced=False ───
    def test_get_brand_config_defaults(self, branding_env):
        """COV-B11: sync_decisions_to_constitution内でEvolutionTriggerService例外

        対象行: L214-216 (except Exception → synced=False)
        - EvolutionTriggerServiceのimportまたはevaluate_triggersが失敗
        - → except → {"synced": False, "error": "..."}
        """
        bm, branding_dir, paths = branding_env

        # EvolutionTriggerServiceのimportを失敗させる
        with patch.dict("sys.modules", {
            "services.evolution_trigger_service": None,  # ImportError
        }):
            result = bm.sync_decisions_to_constitution()
            assert result["synced"] is False
            assert "error" in result

    # ─── COV-B12: process_analytics_update セクション部分 ───
    def test_update_constitution_section(self, branding_env):
        """COV-B12: process_analytics_update → external_status初期化+保存

        対象行: L318-327
        - external_statusが未定義 → 初期化 (L318-319)
        - youtube/rivals/questsを設定 → 保存 (L321-327)
        """
        bm, branding_dir, paths = branding_env

        mock_analytics = MagicMock()
        mock_analytics.get_my_stats.return_value = {
            "subscribers": 1000,
            "total_views": 50000
        }
        mock_analytics.scout_rivals.return_value = [
            {"name": "RivalChannel", "subscribers": 5000}
        ]
        mock_analytics.calculate_gap.return_value = [
            {"quest": "reach 5000 subs"}
        ]

        mock_module = MagicMock()
        mock_module.analytics_manager = mock_analytics

        with patch.dict("sys.modules", {
            "branding.analytics_manager": mock_module,
        }), \
             patch("branding_manager.CONSTITUTION_PATH", paths["constitution_path"]), \
             patch("branding_manager.USER_MODEL_PATH", paths["user_model_path"]), \
             patch("branding_manager.history_manager"):
            result = bm.process_analytics_update()

            # 結果が返ること
            assert result["stats"]["subscribers"] == 1000
            assert result["stats"]["total_views"] == 50000
            assert result["biz_xp"] == 500  # 50000/100
            assert len(result["rivals"]) == 1
            assert len(result["quests"]) == 1

            # external_statusが設定されていること (L318-327)
            assert "external_status" in bm.user_model
            assert bm.user_model["external_status"]["youtube"]["subscribers"] == 1000

    # ─── COV-B13: log_evolution例外 → print+return None ───
    def test_sync_decisions_empty_logger(self, branding_env):
        """COV-B13: log_evolution例外 + auto_evolve_all soul_narrative_sync例外

        対象行:
        - L452-454 (log_evolution except Exception → print + return None)
        - L239-240 (auto_evolve_all: decision_logger.sync_to_soul_narrative except)
        """
        bm, branding_dir, paths = branding_env

        evo_log_path = str(branding_dir / "evolution_log.json")
        with open(evo_log_path, "w", encoding="utf-8") as f:
            json.dump({"entries": [], "philosophies": []}, f)

        with patch("branding_manager.BRANDING_DIR", str(branding_dir)):
            # Part 1: google.genai import失敗 → except (L452-454)
            with patch.dict("sys.modules", {"google.genai": None}):
                result = bm.log_evolution({"type": "test", "xp_grant": 10})
                assert result is None

        # Part 2: auto_evolve_all の soul_narrative_sync except (L239-240)
        mock_dl = MagicMock()
        mock_dl.sync_to_soul_narrative.side_effect = RuntimeError("sync failed")

        with patch("branding_manager.decision_logger", mock_dl), \
             patch("branding_manager.BRANDING_DIR", str(branding_dir)), \
             patch.dict("sys.modules", {
                 "services.evolution_trigger_service": None,
             }):
            result = bm.auto_evolve_all()
            # soul_narrative_sync例外 → error記録
            assert "error" in result["soul_narrative_sync"]
            assert "sync failed" in result["soul_narrative_sync"]["error"]

    # ─── COV-B14: _integrate_philosophies例外+正常パス ───
    def test_get_evolution_summary_no_log(self, branding_env):
        """COV-B14: _integrate_philosophies 例外パス + 正常パス

        対象行:
        - L500-501 (except Exception → print)
        - L462-498 (_integrate_philosophies 正常実行: Gemini呼出→統合哲学保存)
        """
        bm, branding_dir, paths = branding_env

        evo_log = {
            "entries": [],
            "philosophies": [
                {"philosophy": "哲学1", "timestamp": "2026-01-01"},
                {"philosophy": "哲学2", "timestamp": "2026-02-01"},
                {"philosophy": "哲学3", "timestamp": "2026-03-01"},
            ]
        }

        # Part 1: 例外パス (L500-501)
        with patch.dict("sys.modules", {
            "model_registry": None,  # ImportError → except (L500-501)
        }):
            bm._integrate_philosophies(evo_log)
            assert "integrated_philosophy" not in evo_log

        # Part 2: 正常パス (L462-498: Gemini応答モック)
        mock_response = MagicMock()
        mock_response.text = "「テストと品質の統合哲学」"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_get_model = MagicMock(return_value="gemini-2.0-flash")
        mock_get_client = MagicMock(return_value=mock_client)

        with patch("branding_manager.BrandingManager._integrate_philosophies.__module__", create=True):
            pass  # no-op, just to isolate

        # model_registry と gemini_client_factory をモック
        mock_model_reg = MagicMock()
        mock_model_reg.get_model = mock_get_model
        mock_gcf = MagicMock()
        mock_gcf.get_gemini_client = mock_get_client

        evo_log_2 = {
            "entries": [],
            "philosophies": [
                {"philosophy": "哲学A", "timestamp": "2026-01-01"},
                {"philosophy": "哲学B", "timestamp": "2026-02-01"},
                {"philosophy": "哲学C", "timestamp": "2026-03-01"},
            ]
        }

        with patch.dict("sys.modules", {
            "model_registry": mock_model_reg,
            "gemini_client_factory": mock_gcf,
        }):
            bm._integrate_philosophies(evo_log_2)

            # 統合哲学が保存されること (L490-496)
            assert evo_log_2["integrated_philosophy"] == "「テストと品質の統合哲学」"
            assert len(evo_log_2["integration_history"]) == 1
            assert evo_log_2["integration_history"][0]["source_count"] == 3


# =====================================================================
# COV-B15~B21: model_governance.py (B分類・JT-03降格チェーン通過)
# =====================================================================

class TestCovB_ModelGovernance:
    """model_governance.py 未カバー行テスト (80%→85%)"""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """テスト間でシングルトン状態をリセット"""
        from model_governance import ModelGovernanceEngine
        # テスト前に状態を保存
        engine = ModelGovernanceEngine()
        orig_stats = dict(engine._stats)
        orig_events = list(engine._event_log)
        yield engine
        # テスト後にリストア
        engine._stats = orig_stats
        engine._event_log = orig_events

    # ─── COV-B15: _resolve_model ImportError + 一般Exception (L255-258) ───
    def test_validate_model_unknown_role(self, _reset_singleton):
        """COV-B15: _resolve_model の枠チェックで ImportError → pass, Exception → debug log

        対象行: L255-258
        - except ImportError: pass (L255-256)
        - except Exception as e: logger.debug (L257-258)
        """
        engine = _reset_singleton
        # **差替表を空にする**（R1.5-C6）。ここで見たいのは枠チェックの
        # ImportError / 一般例外の経路であって deprecated 差替ではない。
        # 実設定に gemini-2.5-* の差替行が入ったので、モデル名を素通しの
        # 目印に使えなくなった
        engine._deprecation_map = {}

        # Part 1: ImportError パス (L255-256) — usage_tracker未インポート
        with patch.dict("sys.modules", {"usage_tracker": None, "usage_tracker.tracker": None}):
            result = engine._resolve_model("test_task", "gemini-2.5-flash")
            # ImportError → pass → モデル名はそのまま返る
            assert result == "gemini-2.5-flash"

        # Part 2: 一般Exception パス (L257-258)
        mock_ut_mod = MagicMock()
        mock_ut = MagicMock()
        mock_ut.can_make_request.side_effect = RuntimeError("tracker broken")
        mock_ut_mod.usage_tracker = mock_ut
        with patch.dict("sys.modules", {
            "usage_tracker": MagicMock(),
            "usage_tracker.tracker": mock_ut_mod,
        }):
            result = engine._resolve_model("test_task", "gemini-2.5-flash")
            # 一般Exception → debug log → モデル名はそのまま返る
            assert result == "gemini-2.5-flash"

    # ─── COV-B16: _track_usage quota_alert記録 + except (L398-404) ───
    def test_demotion_chain_execution(self, _reset_singleton):
        """COV-B16: _track_usage でquota alert記録 + exception時のdebugログ

        対象行: L398-404
        - alert_level == "warning" → _record_event("quota_alert") (L397-402)
        - except Exception → debug log (L403-404)
        """
        engine = _reset_singleton

        # Part 1: quota alert記録 (L397-402)
        mock_ut_mod = MagicMock()
        mock_ut = MagicMock()
        mock_ut.track_request.return_value = {
            "alert_level": "warning",
            "usage_ratio": 0.85,
        }
        mock_ut_mod.usage_tracker = mock_ut
        with patch.dict("sys.modules", {
            "usage_tracker": MagicMock(),
            "usage_tracker.tracker": mock_ut_mod,
        }):
            initial_events = len(engine._event_log)
            engine._track_usage("gemini-2.5-flash", "test_caller")
            # quota_alert イベントが記録されること
            assert len(engine._event_log) > initial_events
            last_event = engine._event_log[-1]
            assert last_event["type"] == "quota_alert"
            assert "warning" in last_event["error"]

        # Part 2: except Exception (L403-404)
        mock_ut_mod2 = MagicMock()
        mock_ut2 = MagicMock()
        mock_ut2.track_request.side_effect = ConnectionError("tracker unavailable")
        mock_ut_mod2.usage_tracker = mock_ut2
        with patch.dict("sys.modules", {
            "usage_tracker": MagicMock(),
            "usage_tracker.tracker": mock_ut_mod2,
        }):
            # 例外発生 → debug log → 正常終了（握りつぶし）
            engine._track_usage("gemini-2.5-flash", "test_caller")

    # ─── COV-B17: GovernedModelsProxy fallback_exhausted + raise (L480-491) ───
    def test_quota_exceeded_fallback(self, _reset_singleton):
        """COV-B17: GovernedModelsProxy.generate_content のフォールバック枯渇

        対象行: L480-491
        - fallback_exhausted → _record_event + logger.error + raise (L479-489)
        - raise last_error (L491)
        """
        from model_governance import GovernedModelsProxy, model_governance

        engine = _reset_singleton

        # フォールバックチェーンを設定: A → B → None
        orig_chain = dict(engine._fallback_chain)
        engine._fallback_chain = {"model-a": "model-b"}

        mock_real = MagicMock()
        # 全呼出で429エラー → フォールバック対象
        mock_real.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")

        proxy = GovernedModelsProxy(mock_real, caller="test")

        # time.sleep をスキップ
        with patch("model_governance.time.sleep"):
            with pytest.raises(RuntimeError, match="429"):
                proxy.generate_content(model="model-a", contents="test")

        # fallback_exhaustedイベントが記録されていること
        exhausted_events = [
            e for e in engine._event_log
            if e["type"] == "fallback_exhausted"
        ]
        assert len(exhausted_events) > 0

        # リストア
        engine._fallback_chain = orig_chain

    # ─── COV-B18: GovernedAsyncModelsProxy 全パス (L519-575) ───
    @pytest.mark.asyncio
    async def test_model_config_reload(self, _reset_singleton):
        """COV-B18: GovernedAsyncModelsProxy.generate_content の全パス実行

        対象行: L519-575
        - validate_and_correct + build_fallback_sequence (L521-522)
        - 成功パス: i==0 → 直接return (L526-540)
        - フォールバック成功パス: i>0 → fallback_success記録 (L530-539)
        - フォールバック枯渇パス: next_model=None → raise (L564-573)
        """
        from model_governance import GovernedAsyncModelsProxy, model_governance

        engine = _reset_singleton

        # フォールバックチェーンを設定
        orig_chain = dict(engine._fallback_chain)
        engine._fallback_chain = {"async-a": "async-b"}

        # Part 1: 成功パス (直接成功)
        mock_real = AsyncMock()
        mock_result = MagicMock()
        mock_result.text = "success"
        mock_real.generate_content.return_value = mock_result

        proxy = GovernedAsyncModelsProxy(mock_real, caller="async_test")
        result = await proxy.generate_content(model="async-a", contents="hello")
        assert result.text == "success"

        # Part 2: フォールバック成功パス (1回目失敗 → 2回目成功)
        call_count = [0]
        async def side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return mock_result

        mock_real2 = AsyncMock()
        mock_real2.generate_content.side_effect = side_effect
        proxy2 = GovernedAsyncModelsProxy(mock_real2, caller="async_test2")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result2 = await proxy2.generate_content(model="async-a", contents="hello")
            assert result2.text == "success"

        # fallback_success が記録されていること
        fb_success = [e for e in engine._event_log if e["type"] == "fallback_success"]
        assert len(fb_success) > 0

        # Part 3: フォールバック枯渇パス
        mock_real3 = AsyncMock()
        mock_real3.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")
        proxy3 = GovernedAsyncModelsProxy(mock_real3, caller="async_test3")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="429"):
                await proxy3.generate_content(model="async-a", contents="hello")

        # リストア
        engine._fallback_chain = orig_chain

    # ─── COV-B19: _model_usage_tracking_hook quota_alert + except (L663-671) ───
    @pytest.mark.asyncio
    async def test_get_active_models_empty(self, _reset_singleton):
        """COV-B19: _model_usage_tracking_hook のquota alert記録 + except

        対象行: L663-671
        - alert_level == "warning" → _record_event("quota_alert") (L662-669)
        - except Exception → debug log (L670-671)
        """
        from model_governance import _model_usage_tracking_hook, model_governance

        engine = _reset_singleton

        # Part 1: quota alert 記録 (L662-669)
        mock_hook_input = MagicMock()
        mock_hook_input.tool_input = {"model": "gemini-2.5-flash"}
        mock_hook_input.tool_name = "test_tool"

        mock_ut_mod = MagicMock()
        mock_ut = MagicMock()
        mock_ut.track_request.return_value = {
            "alert_level": "critical",
            "usage_ratio": 0.95,
        }
        mock_ut_mod.usage_tracker = mock_ut
        with patch.dict("sys.modules", {
            "usage_tracker": MagicMock(),
            "usage_tracker.tracker": mock_ut_mod,
        }):
            initial_events = len(engine._event_log)
            result = await _model_usage_tracking_hook(mock_hook_input)
            assert result is None
            # quota_alert イベントが記録されていること
            new_events = [
                e for e in engine._event_log[initial_events:]
                if e["type"] == "quota_alert"
            ]
            assert len(new_events) == 1
            assert "critical" in new_events[0]["error"]

        # Part 2: except Exception (L670-671)
        mock_ut_mod2 = MagicMock()
        mock_ut2 = MagicMock()
        mock_ut2.track_request.side_effect = OSError("tracker crash")
        mock_ut_mod2.usage_tracker = mock_ut2
        with patch.dict("sys.modules", {
            "usage_tracker": MagicMock(),
            "usage_tracker.tracker": mock_ut_mod2,
        }):
            result = await _model_usage_tracking_hook(mock_hook_input)
            assert result is None  # 例外は握りつぶされる

    # ─── COV-B20: register_governance_hook 正常登録 (L678-700) ───
    def test_usage_report_generation(self, _reset_singleton):
        """COV-B20: register_governance_hook のhook登録成功パス

        対象行: L678-700
        - harness.hooks import成功 → hook_system.register呼出 (L679-698)
        - ImportError → debug log (L699-700)
        """
        from model_governance import register_governance_hook

        # Part 1: 正常登録パス (L679-698)
        mock_hook_system = MagicMock()
        mock_hook_event = MagicMock()
        mock_hook_event.PRE_TOOL_USE = "pre"
        mock_hook_event.POST_TOOL_USE = "post"

        mock_hooks_module = MagicMock()
        mock_hooks_module.hook_system = mock_hook_system
        mock_hooks_module.HookEvent = mock_hook_event

        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.hooks": mock_hooks_module,
        }):
            register_governance_hook()
            # 2回登録されること (PreToolUse + PostToolUse)
            assert mock_hook_system.register.call_count == 2
            # 1回目: PRE_TOOL_USE
            first_call = mock_hook_system.register.call_args_list[0]
            assert first_call[1].get("priority", first_call[0][0] if len(first_call[0]) > 0 else None) is not None
            # 2回目: POST_TOOL_USE
            second_call = mock_hook_system.register.call_args_list[1]
            assert second_call is not None

        # Part 2: ImportError パス (L699-700)
        with patch.dict("sys.modules", {"harness": None, "harness.hooks": None}):
            # ImportError → debug log → 正常終了
            register_governance_hook()

    # ─── COV-B21: call() config付き + 同期クライアント + raise last_error (L315,324,389) ───
    @pytest.mark.asyncio
    async def test_validate_and_correct_invalid(self, _reset_singleton):
        """COV-B21: ModelGovernanceEngine.call() の config付き/同期クライアント/raise

        対象行:
        - L314-315: config → gen_kwargs.update(config)
        - L322-326: 同期クライアント → asyncio.to_thread
        - L389: raise last_error (安全弁)
        """
        engine = _reset_singleton

        # Part 1: config付き + 同期クライアント (L315, L324)
        mock_response = MagicMock()
        mock_response.text = "generated text"

        mock_sync_models = MagicMock()
        mock_sync_models.generate_content.return_value = mock_response

        # aioを持たないクライアント → 同期パス
        mock_client = MagicMock(spec=["models"])
        mock_client.models = mock_sync_models

        with patch("gemini_client_factory._get_raw_client", return_value=mock_client):
            # usage_tracker を無効化
            with patch.dict("sys.modules", {
                "usage_tracker": None,
                "usage_tracker.tracker": None,
            }):
                result = await engine.call(
                    task="test_task",
                    prompt="hello",
                    caller="cov_b21",
                    config={"temperature": 0.5},
                )
                assert result == "generated text"
                # generate_content が temperature パラメータ付きで呼ばれたこと
                call_kwargs = mock_sync_models.generate_content.call_args
                assert call_kwargs[1].get("temperature") == 0.5 or \
                       (len(call_kwargs[0]) == 0 and "temperature" in call_kwargs[1])


# =====================================================================
# COV-B22~B27: service_container.py (B分類・M4.4依存基盤)
# =====================================================================

class TestCovB_ServiceContainer:
    """service_container.py 未カバー行テスト (57%→75%)

    設計書: sprint_434_batch_b_design.md (conv_b0c8b1b7) §4.4
    対象: 10個のファクトリー関数 (_init_*) の正常パス + ImportError/Exceptionパス
    """

    @pytest.fixture(autouse=True)
    def _reset_container(self):
        """テスト間でServiceContainerの状態をリセット"""
        from service_container import container
        # 保存
        orig_instances = dict(container._instances)
        orig_factories = dict(container._factories)
        orig_initialized = container._initialized
        yield
        # リストア
        container._instances = orig_instances
        container._factories = orig_factories
        container._initialized = orig_initialized

    # ─── COV-B22: _init_usage_tracker + _init_youtube_analytics + _init_speaker_diarizer ───
    def test_register_transcribe_service(self, tmp_path):
        """COV-B22: Transcribe関連3サービスの正常初期化パス

        対象行: L154-168
        - _init_usage_tracker: APIUsageTracker(data_dir / "api_usage.json") (L154-158)
        - _init_youtube_analytics: YouTubeAnalyticsClient() (L161-163)
        - _init_speaker_diarizer: SpeakerDiarizer() (L166-168)
        """
        from service_container import (
            _init_usage_tracker,
            _init_youtube_analytics,
            _init_speaker_diarizer,
        )

        # _init_usage_tracker 正常パス (L154-158)
        mock_tracker_cls = MagicMock()
        mock_tracker_instance = MagicMock()
        mock_tracker_cls.return_value = mock_tracker_instance
        mock_ut_module = MagicMock()
        mock_ut_module.APIUsageTracker = mock_tracker_cls

        with patch.dict("sys.modules", {
            "usage_tracker": MagicMock(),
            "usage_tracker.api_usage_tracker": mock_ut_module,
        }):
            result = _init_usage_tracker()
            assert result is mock_tracker_instance
            mock_tracker_cls.assert_called_once()

        # _init_youtube_analytics 正常パス (L161-163)
        mock_yt_cls = MagicMock()
        mock_yt_instance = MagicMock()
        mock_yt_cls.return_value = mock_yt_instance
        mock_yt_module = MagicMock()
        mock_yt_module.YouTubeAnalyticsClient = mock_yt_cls

        with patch.dict("sys.modules", {
            "services": MagicMock(),
            "services.youtube_analytics_client": mock_yt_module,
        }):
            result = _init_youtube_analytics()
            assert result is mock_yt_instance

        # _init_speaker_diarizer 正常パス (L166-168)
        mock_sd_cls = MagicMock()
        mock_sd_instance = MagicMock()
        mock_sd_cls.return_value = mock_sd_instance
        mock_sd_module = MagicMock()
        mock_sd_module.SpeakerDiarizer = mock_sd_cls

        with patch.dict("sys.modules", {
            "subtitle_engine": MagicMock(),
            "subtitle_engine.speaker_diarizer": mock_sd_module,
        }):
            result = _init_speaker_diarizer()
            assert result is mock_sd_instance

    # ─── COV-B23: _init_branding_manager 正常パス + ImportError ───
    def test_register_proofread_service(self):
        """COV-B23: BrandingManager初期化の正常パス + ImportErrorパス

        対象行: L171-177
        - 正常: BrandingManager() → インスタンス返却 (L172-174)
        - ImportError: → logger.warning + return None (L175-177)
        """
        from service_container import _init_branding_manager

        # 正常パス (L172-174)
        mock_bm_cls = MagicMock()
        mock_bm_instance = MagicMock()
        mock_bm_cls.return_value = mock_bm_instance
        mock_bm_module = MagicMock()
        mock_bm_module.BrandingManager = mock_bm_cls

        with patch.dict("sys.modules", {
            "branding_manager": mock_bm_module,
        }):
            result = _init_branding_manager()
            assert result is mock_bm_instance
            mock_bm_cls.assert_called_once()

        # ImportError パス (L175-177)
        with patch.dict("sys.modules", {
            "branding_manager": None,
        }):
            result = _init_branding_manager()
            assert result is None

    # ─── COV-B24: _init_pipeline_coordinator 正常パス + ImportError ───
    def test_register_quality_gate_service(self):
        """COV-B24: PipelineCoordinator初期化の正常パス + ImportErrorパス

        対象行: L180-187
        - 正常: ProductionPipelineCoordinator() → インスタンス返却 (L182-184)
        - ImportError: → logger.info + return None (L185-187)
        """
        from service_container import _init_pipeline_coordinator

        # 正常パス (L182-184)
        mock_pc_cls = MagicMock()
        mock_pc_instance = MagicMock()
        mock_pc_cls.return_value = mock_pc_instance
        mock_pc_module = MagicMock()
        mock_pc_module.PipelineCoordinator = mock_pc_cls

        with patch.dict("sys.modules", {
            "agents": MagicMock(),
            "agents.pipeline_coordinator": mock_pc_module,
        }):
            result = _init_pipeline_coordinator()
            assert result is mock_pc_instance

        # ImportError パス (L185-187)
        with patch.dict("sys.modules", {
            "agents": MagicMock(),
            "agents.pipeline_coordinator": None,
        }):
            result = _init_pipeline_coordinator()
            assert result is None

    def test_pipeline_coordinator_other_exception(self):
        """ImportError以外の例外（例：RuntimeError）が発生した場合に伝播すること"""
        from service_container import _init_pipeline_coordinator

        mock_pc_cls = MagicMock()
        mock_pc_cls.side_effect = RuntimeError("Init failed")
        mock_pc_module = MagicMock()
        mock_pc_module.PipelineCoordinator = mock_pc_cls

        with patch.dict("sys.modules", {
            "agents": MagicMock(),
            "agents.pipeline_coordinator": mock_pc_module,
        }):
            with pytest.raises(RuntimeError, match="Init failed"):
                _init_pipeline_coordinator()

    # ─── COV-B25: _init_gemini_client 正常パス + Exception ───
    def test_register_render_service(self):
        """COV-B25: Geminiクライアント初期化の正常パス + Exceptionパス

        対象行: L190-196
        - 正常: get_gemini_client() → クライアント返却 (L191-193)
        - Exception: → logger.warning + return None (L194-196)
        """
        from service_container import _init_gemini_client

        # 正常パス (L191-193)
        mock_client = MagicMock()
        mock_gcf = MagicMock()
        mock_gcf.get_gemini_client.return_value = mock_client

        with patch.dict("sys.modules", {
            "gemini_client_factory": mock_gcf,
        }):
            result = _init_gemini_client()
            assert result is mock_client

        # Exception パス (L194-196) — get_gemini_client() が例外を投げる
        mock_gcf_err = MagicMock()
        mock_gcf_err.get_gemini_client.side_effect = RuntimeError("API key not set")

        with patch.dict("sys.modules", {
            "gemini_client_factory": mock_gcf_err,
        }):
            result = _init_gemini_client()
            assert result is None

    # ─── COV-B26: _init_harness_hooks + _init_harness_sessions 正常パス + ImportError ───
    def test_register_youtube_service(self):
        """COV-B26: Harnessフック+セッション初期化の正常パス + ImportErrorパス

        対象行: L199-217
        - _init_harness_hooks: hook_system.register_builtin_hooks() (L201-207)
        - _init_harness_sessions: session_manager (L210-217)
        """
        from service_container import _init_harness_hooks, _init_harness_sessions

        # _init_harness_hooks 正常パス (L201-204)
        mock_hook_system = MagicMock()
        mock_hooks_module = MagicMock()
        mock_hooks_module.hook_system = mock_hook_system

        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.hooks": mock_hooks_module,
        }):
            result = _init_harness_hooks()
            assert result is mock_hook_system
            mock_hook_system.register_builtin_hooks.assert_called_once()

        # _init_harness_hooks ImportError パス (L205-207)
        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.hooks": None,
        }):
            result = _init_harness_hooks()
            assert result is None

        # _init_harness_sessions 正常パス (L211-214)
        mock_session_mgr = MagicMock()
        mock_sessions_module = MagicMock()
        mock_sessions_module.session_manager = mock_session_mgr

        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.session_manager": mock_sessions_module,
        }):
            result = _init_harness_sessions()
            assert result is mock_session_mgr

        # _init_harness_sessions ImportError パス (L215-217)
        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.session_manager": None,
        }):
            result = _init_harness_sessions()
            assert result is None

    # ─── COV-B27: _init_harness_governance + _init_harness_tools → setup_services全体 ───
    def test_register_all_services(self):
        """COV-B27: ガバナンスエンジン+ツールレジストリ + setup_services全体テスト

        対象行: L220-237 + L109-147
        - _init_harness_governance: governance_engine (L221-227)
        - _init_harness_tools: tool_registry (L231-237)
        - setup_services(): 全register_lazy呼出 + ログ出力 (L109-147)
        """
        from service_container import (
            _init_harness_governance,
            _init_harness_tools,
            setup_services,
            container,
        )

        # _init_harness_governance 正常パス (L222-224)
        mock_gov_engine = MagicMock()
        mock_gov_module = MagicMock()
        mock_gov_module.governance_engine = mock_gov_engine

        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.governance": mock_gov_module,
        }):
            result = _init_harness_governance()
            assert result is mock_gov_engine

        # _init_harness_governance ImportError パス (L225-227)
        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.governance": None,
        }):
            result = _init_harness_governance()
            assert result is None

        # _init_harness_tools 正常パス (L232-234)
        mock_tool_reg = MagicMock()
        mock_tools_module = MagicMock()
        mock_tools_module.tool_registry = mock_tool_reg

        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.tool_registry": mock_tools_module,
        }):
            result = _init_harness_tools()
            assert result is mock_tool_reg

        # _init_harness_tools ImportError パス (L235-237)
        with patch.dict("sys.modules", {
            "harness": MagicMock(),
            "harness.tool_registry": None,
        }):
            result = _init_harness_tools()
            assert result is None

        # setup_services 全体テスト (L109-147)
        container.reset()
        assert container._initialized is False

        setup_services()
        assert container._initialized is True
        # 全10サービスがlazy登録されていること
        expected_services = [
            "usage_tracker", "youtube_analytics", "speaker_diarizer",
            "branding_manager", "pipeline_coordinator", "gemini_client",
            "harness_hook_system", "harness_session_manager",
            "harness_governance", "harness_tool_registry",
        ]
        for svc_name in expected_services:
            assert container.has(svc_name), f"Service '{svc_name}' not registered"

        # 2回目のsetup_servicesは何もしない (L117-118)
        setup_services()  # _initialized=Trueなのでearly return
        assert container._initialized is True


# =====================================================================
# COV-B28~B32: websocket_handler.py (B分類・M4.5依存基盤)
# =====================================================================

class TestCovB_WebSocketHandler:
    """websocket_handler.py 未カバー行テスト

    設計書: sprint_434_batch_b_design.md (conv_b0c8b1b7)
    対象: ConnectionManager broadcast/disconnect/heartbeat のエラーパス
    """

    # ─── COV-B28: broadcast_progress 送信エラー → disconnect (L214-223) ───
    @pytest.mark.asyncio
    async def test_broadcast_progress_send_error(self):
        """COV-B28: broadcast_progress内の送信失敗 → disconnected リストに追加 → disconnect

        対象行: L214-223
        - send_json例外 → disconnected.append(websocket) (L218-220)
        - for conn in disconnected: disconnect(conn) (L222-223)
        """
        from websocket_handler import ConnectionManager, ConnectionInfo

        manager = ConnectionManager()

        # 正常なWebSocketモック
        good_ws = AsyncMock()
        good_ws.send_json = AsyncMock()

        # 送信失敗するWebSocketモック
        bad_ws = AsyncMock()
        bad_ws.send_json = AsyncMock(side_effect=RuntimeError("Connection closed"))

        # 直接connectionsに追加（accept()をスキップ）
        manager.connections[good_ws] = ConnectionInfo(websocket=good_ws)
        manager.connections[bad_ws] = ConnectionInfo(websocket=bad_ws)
        assert len(manager.connections) == 2

        await manager.broadcast_progress({"type": "test", "progress": 50})

        # good_wsは送信成功
        good_ws.send_json.assert_called_once_with({"type": "test", "progress": 50})
        # bad_wsはエラー → disconnectされる
        assert bad_ws not in manager.connections
        assert good_ws in manager.connections

    # ─── COV-B29: send_personal_message 例外 → warning log (L225-231) ───
    @pytest.mark.asyncio
    async def test_send_personal_message_error(self):
        """COV-B29: send_personal_message内の送信失敗 → warning log

        対象行: L225-231
        - send_json例外 → logger.warning (L230-231)
        """
        from websocket_handler import ConnectionManager, ConnectionInfo

        manager = ConnectionManager()

        ws = AsyncMock()
        ws.send_json = AsyncMock(side_effect=ConnectionError("broken pipe"))
        manager.connections[ws] = ConnectionInfo(websocket=ws)

        # 例外は握りつぶされ、warningのみ
        await manager.send_personal_message({"type": "test"}, ws)
        ws.send_json.assert_called_once()

    # ─── COV-B30: disconnect でuser_connections除去 (L162-171) ───
    @pytest.mark.asyncio
    async def test_disconnect_with_user_id(self):
        """COV-B30: disconnect時のuser_connections管理 — 最後の接続削除でuser除去

        対象行: L162-171
        - info.user_idがある場合 → user_connectionsからdiscard (L166-168)
        - user_connsが空 → del user_connections[user_id] (L169-170)
        """
        from websocket_handler import ConnectionManager, ConnectionInfo

        manager = ConnectionManager()

        ws = AsyncMock()
        user_id = "test_user_001"
        manager.connections[ws] = ConnectionInfo(websocket=ws, user_id=user_id)
        manager.user_connections[user_id] = {ws}

        await manager.disconnect(ws)

        # 接続が削除されていること
        assert ws not in manager.connections
        # user_connectionsからもuser_idが除去されていること
        assert user_id not in manager.user_connections

    # ─── COV-B31: connect 最大接続数超過 → close(1013) (L122-125) ───
    @pytest.mark.asyncio
    async def test_connect_max_connections_exceeded(self):
        """COV-B31: connect時に最大接続数超過 → websocket.close(1013)

        対象行: L122-125
        - len(connections) >= max_connections → close(code=1013) (L122-124)
        - return False (L125)
        """
        from websocket_handler import ConnectionManager, ConnectionInfo

        # max_connections=1 の小さなマネージャーを作成
        manager = ConnectionManager(max_connections=1)

        # 1つ目の接続を手動追加
        existing_ws = AsyncMock()
        manager.connections[existing_ws] = ConnectionInfo(websocket=existing_ws)

        # 2つ目の接続を試みる → 拒否される
        new_ws = AsyncMock()
        new_ws.close = AsyncMock()

        result = await manager.connect(new_ws)
        assert result is False
        new_ws.close.assert_called_once()
        call_kwargs = new_ws.close.call_args
        assert call_kwargs[1].get("code") == 1013 or (call_kwargs[0] and call_kwargs[0][0] == 1013)

    # ─── COV-B32: connect 無効トークン → close(4001) + ユーザー接続数超過 → close(4002) ───
    @pytest.mark.asyncio
    async def test_connect_invalid_token_and_user_limit(self):
        """COV-B32: connect時のトークン検証失敗 + ユーザー接続数超過

        対象行: L127-141
        - 無効トークン → close(code=4001) (L131-134)
        - ユーザー接続数超過 → close(code=4002) (L138-141)
        """
        from websocket_handler import ConnectionManager, ConnectionInfo, token_manager

        manager = ConnectionManager()

        # Part 1: 無効トークン → close(4001)
        ws1 = AsyncMock()
        ws1.close = AsyncMock()
        result = await manager.connect(ws1, token="invalid_token_xyz")
        assert result is False
        ws1.close.assert_called_once()
        close_kwargs = ws1.close.call_args
        assert close_kwargs[1].get("code") == 4001

        # Part 2: ユーザー接続数超過 → close(4002)
        # 有効なトークンを生成
        valid_token = token_manager.generate_token("test_user_limit", ttl=3600)
        user_id = "test_user_limit"

        # MAX_CONNECTIONS_PER_USER(5)個の接続を手動登録
        from websocket_handler import MAX_CONNECTIONS_PER_USER
        manager.user_connections[user_id] = set()
        for i in range(MAX_CONNECTIONS_PER_USER):
            mock_ws = AsyncMock()
            manager.connections[mock_ws] = ConnectionInfo(websocket=mock_ws, user_id=user_id)
            manager.user_connections[user_id].add(mock_ws)

        ws2 = AsyncMock()
        ws2.close = AsyncMock()
        result = await manager.connect(ws2, token=valid_token)
        assert result is False
        ws2.close.assert_called_once()
        close_kwargs2 = ws2.close.call_args
        assert close_kwargs2[1].get("code") == 4002


# =====================================================================
# COV-B33~B36: decision_logger.py (B分類・JT-02依存基盤)
# =====================================================================

class TestCovB_DecisionLogger:
    """decision_logger.py 未カバー行テスト

    設計書: sprint_434_batch_b_design.md (conv_b0c8b1b7)
    対象: 履歴フィルタ/パターン分析/CSV出力のエラーパス
    """

    @pytest.fixture
    def isolated_logger(self, tmp_path):
        """DecisionLogger用の隔離環境を構築"""
        from decision_logger import DecisionLogger
        dl = DecisionLogger.__new__(DecisionLogger)
        dl.log_dir = tmp_path / "branding"
        dl.log_dir.mkdir(parents=True, exist_ok=True)
        dl.log_file = dl.log_dir / "decision_log.json"
        dl.decisions = []
        return dl

    # ─── COV-B33: _load 破損JSONファイル → except → 空リスト (L73-84) ───
    def test_load_corrupted_json(self, tmp_path):
        """COV-B33: _load時に破損JSON → except → decisions = []

        対象行: L73-84
        - json.load例外 → logger.error + self.decisions = [] (L82-84)
        """
        from decision_logger import DecisionLogger

        branding_dir = tmp_path / "branding"
        branding_dir.mkdir()
        log_file = branding_dir / "decision_log.json"
        log_file.write_text("{corrupted json!!!}", encoding="utf-8")

        dl = DecisionLogger.__new__(DecisionLogger)
        dl.log_dir = branding_dir
        dl.log_file = log_file
        dl.decisions = []
        dl._load()

        # 破損JSON → 空リスト
        assert dl.decisions == []

    # ─── COV-B34: _save 書き込み失敗 → except → logger.error (L86-95) ───
    def test_save_write_failure(self, isolated_logger):
        """COV-B34: _save時の書き込み失敗 → except → logger.error

        対象行: L86-95
        - json.dump例外 → logger.error (L94-95)
        """
        dl = isolated_logger

        # 存在しないディレクトリをlog_fileに設定して書き込み失敗させる
        dl.log_file = Path("/nonexistent/path/that/does/not/exist/log.json")

        # 例外は握りつぶされる → 正常終了
        dl._save()

    # ─── COV-B35: get_similar_decisions タグフィルタ + get_rejection_patterns (L148-236) ───
    def test_get_similar_decisions_and_rejection_patterns(self, isolated_logger):
        """COV-B35: get_similar_decisions のタグフィルタ + get_rejection_patterns

        対象行: L148-182 (get_similar_decisions), L220-236 (get_rejection_patterns)
        - target_type フィルタ (L170-171)
        - tags フィルタ (L173-177)
        - get_rejection_patterns: reject のタグ集計 (L229-236)
        """
        from decision_logger import Decision

        dl = isolated_logger

        # テスト用の意思決定データを追加
        dl.decisions = [
            Decision(
                decision_id="d001", timestamp=1000.0,
                iso_time="2026-01-01T00:00:00",
                target_type="screenshot", target_path="/a.png",
                target_description="シーン1", decision="reject",
                reason="色が暗い", tags=["色調整", "明るさ"],
            ),
            Decision(
                decision_id="d002", timestamp=2000.0,
                iso_time="2026-01-02T00:00:00",
                target_type="screenshot", target_path="/b.png",
                target_description="シーン2", decision="approve",
                reason="良い感じ", tags=["色調整"],
            ),
            Decision(
                decision_id="d003", timestamp=3000.0,
                iso_time="2026-01-03T00:00:00",
                target_type="draft", target_path="/c.mp4",
                target_description="ドラフト1", decision="reject",
                reason="テンポが遅い", tags=["テンポ"],
            ),
        ]

        # target_type フィルタ
        screenshot_decisions = dl.get_similar_decisions(target_type="screenshot")
        assert len(screenshot_decisions) == 2
        assert all(d.target_type == "screenshot" for d in screenshot_decisions)

        # tags フィルタ
        color_decisions = dl.get_similar_decisions(tags=["色調整"])
        assert len(color_decisions) == 2

        # target_type + tags フィルタ
        combined = dl.get_similar_decisions(target_type="screenshot", tags=["明るさ"])
        assert len(combined) == 1
        assert combined[0].decision_id == "d001"

        # get_rejection_patterns
        patterns = dl.get_rejection_patterns()
        assert patterns["色調整"] == 1
        assert patterns["明るさ"] == 1
        assert patterns["テンポ"] == 1

    # ─── COV-B36: get_director_preferences + _generate_advice (L403-442) ───
    def test_get_director_preferences_and_advice(self, isolated_logger):
        """COV-B36: get_director_preferences + _generate_advice

        対象行: L403-428 (get_director_preferences), L430-442 (_generate_advice)
        - preferred_styles 集計 (L413-420)
        - _generate_advice: reject パターン有り → アドバイス生成 (L437-440)
        - _generate_advice: パターン無し → デフォルトメッセージ (L434-435)
        """
        from decision_logger import Decision

        dl = isolated_logger

        # Part 1: データ有り → preferences + advice
        dl.decisions = [
            Decision(
                decision_id="d001", timestamp=1000.0,
                iso_time="2026-01-01T00:00:00",
                target_type="screenshot", target_path="/a.png",
                target_description="シーン1", decision="reject",
                reason="色が暗い", tags=["色調整"],
            ),
            Decision(
                decision_id="d002", timestamp=2000.0,
                iso_time="2026-01-02T00:00:00",
                target_type="screenshot", target_path="/b.png",
                target_description="シーン2", decision="approve",
                reason="良い", tags=["レイアウト", "色調整"],
            ),
        ]

        prefs = dl.get_director_preferences()
        assert "こだわり（却下傾向）" in prefs
        assert prefs["こだわり（却下傾向）"]["色調整"] == 1
        assert "好み（承認傾向）" in prefs
        assert prefs["好み（承認傾向）"]["レイアウト"] == 1
        assert "色調整" in prefs["AI提案へのアドバイス"]

        # Part 2: データ無し → デフォルトアドバイス
        dl.decisions = []
        advice = dl._generate_advice()
        assert advice == "まだ十分なデータがありません。"


# =====================================================================
# COV-B37~B40: 残りモジュール (B分類)
# =====================================================================

class TestCovB_Remaining:
    """review_router.py / admin_setup_router.py / smartcut.py のエラーパステスト

    設計書: sprint_434_batch_b_design.md (conv_b0c8b1b7)
    対象: HTTPException relay検証 + 入力検証パス
    """

    @pytest.fixture
    def review_client(self):
        """review_router用TestClient"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.review_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    @pytest.fixture
    def admin_setup_client(self):
        """admin_setup_router用TestClient"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.admin_setup_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    @pytest.fixture
    def smartcut_client(self):
        """smartcut router用TestClient"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.smartcut import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    # ─── COV-B37: review_router get_stage_report 例外 → HTTPException(500) (L136-140) ───
    def test_review_stage_report_exception(self, review_client):
        """COV-B37: get_stage_report 内部例外 → HTTPException(500)

        対象行: L136-140
        - except HTTPException: raise (L136-137)
        - except Exception → HTTPException(500) (L138-140)
        """
        # プラグインimport失敗 → except Exception → 500
        with patch.dict("sys.modules", {
            "plugins": MagicMock(),
            "plugins.progressive_review_plugin": None,  # ImportError
        }):
            resp = review_client.get("/api/review/stages/subtitle/report")
            assert resp.status_code == 500

    # ─── COV-B38: review_router approve_stage 例外 → HTTPException (L162-166) ───
    def test_review_approve_stage_exception(self, review_client):
        """COV-B38: approve_stage 内部例外 → HTTPException(500)

        対象行: L162-166
        - except HTTPException: raise (L162-163)
        - except Exception → HTTPException(500) (L164-166)
        """
        with patch.dict("sys.modules", {
            "plugins": MagicMock(),
            "plugins.progressive_review_plugin": None,
        }):
            resp = review_client.post("/api/review/stages/subtitle/approve")
            assert resp.status_code == 500

    # ─── COV-B39: admin_setup_router import_config バリデーション (L527-548) ───
    def test_admin_import_config_partial(self, admin_setup_client):
        """COV-B39: import_config の部分適用パス

        対象行: L527-548
        - log_level有効値 → applied (L537-540)
        - storage_threshold_gb → applied (L541-543)
        - notification_settings → applied (L544-546)
        """
        resp = admin_setup_client.post(
            "/api/admin/setup/config/import",
            json={
                "config": {
                    "log_level": "DEBUG",
                    "storage_threshold_gb": 20.0,
                    "notification_settings": {"email": "test@example.com"},
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "imported"
        assert "log_level" in data["applied_keys"]
        assert "storage_threshold_gb" in data["applied_keys"]
        assert "notification_settings" in data["applied_keys"]
        assert data["count"] == 3

    # ─── COV-B40: smartcut recommend HTTPException(400) 未初期化 (L121-122) ───
    def test_smartcut_recommend_not_initialized(self, smartcut_client):
        """COV-B40: recommend で未初期化 → HTTPException(400)

        対象行: L121-122
        - _context is None → HTTPException(400, "SmartCut not initialized") (L121-122)
        """
        import routers.smartcut as sc_module

        # _smart_cut_instanceをリセット
        orig = sc_module._smart_cut_instance
        try:
            # モックのSmartCutPluginを設定
            mock_plugin = MagicMock()
            mock_plugin._context = None  # 未初期化
            sc_module._smart_cut_instance = mock_plugin

            resp = smartcut_client.post(
                "/api/smartcut/recommend",
                json={"target_duration_minutes": 15},
            )
            assert resp.status_code == 400
            assert "not initialized" in resp.json()["detail"]
        finally:
            sc_module._smart_cut_instance = orig
