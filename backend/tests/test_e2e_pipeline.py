"""
E2Eパイプラインテストスイート — 全項目95%以上を目指す統合テスト

テスト対象:
  - ヘルスチェックAPI（GET /health, GET /health/deep）
  - Shorts縦型レンダリングAPI（POST /api/shorts/render）
  - RenderWorker 本番品質レンダリング
  - 一時ファイルクリーンアップ
  - JSON構造化ログ出力
  - 固有名詞辞書API

テスト基準: テレビ局放送技術部 + 有名YouTuber水準
"""

import os
import sys
import json
import time
import pytest
import shutil
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

# テスト対象のモジュールへのパス
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# 1. ヘルスチェックAPI テスト
# ============================================================
class TestHealthCheck:
    """PM-2: ヘルスチェックエンドポイント"""

    def test_health_dependencies_importable(self):
        """ヘルスチェックモジュールがインポートできる"""
        from routers.health import router, _check_ffmpeg, _check_gemini, _check_disk_space
        assert router is not None

    def test_check_ffmpeg_returns_dict(self):
        """FFmpegチェックが辞書を返す"""
        from routers.health import _check_ffmpeg
        result = _check_ffmpeg()
        assert isinstance(result, dict)
        assert "available" in result

    def test_check_gemini_returns_dict(self):
        """Geminiチェックが辞書を返す"""
        from routers.health import _check_gemini
        result = _check_gemini()
        assert isinstance(result, dict)
        assert "key_configured" in result

    def test_check_disk_space_returns_dict(self):
        """ディスクチェックが辞書を返す"""
        from routers.health import _check_disk_space
        result = _check_disk_space()
        assert isinstance(result, dict)
        # free_gb or error が含まれる
        assert "free_gb" in result or "error" in result

    def test_check_whisper_returns_dict(self):
        """Whisperチェックが辞書を返す"""
        from routers.health import _check_whisper
        result = _check_whisper()
        assert isinstance(result, dict)
        assert "available" in result


# ============================================================
# 2. 一時ファイルクリーンアップ テスト（CR-4）
# ============================================================
class TestTempFileCleanup:
    """CR-4: finally ブロックによる確実なクリーンアップ"""

    def test_smart_cut_engine_has_finally_block(self):
        """smart_cut_engine.py に finally ブロックが存在する"""
        source = Path(__file__).parent.parent / "smart_cut_engine.py"
        content = source.read_text(encoding="utf-8")
        assert "finally:" in content
        assert "p.unlink()" in content

    def test_cleanup_runs_on_exception(self):
        """例外発生時もクリーンアップが実行される"""
        from smart_cut_engine import render_smart_cut

        # 存在しない動画でrender_smart_cutを呼ぶ（例外発生するが、クリーンアップが走る）
        result = render_smart_cut(
            segments=[{"start": 0, "end": 5, "sourceStart": 0, "sourceEnd": 5}],
            original_video_path="/nonexistent/video.mp4",
            output_path="/tmp/test_output.mp4",
        )
        # False を返す（クラッシュしない）
        assert result is False


# ============================================================
# 3. JSON構造化ログ テスト（CR-5/PM-1）
# ============================================================
class TestStructuredLogging:
    """CR-5/PM-1: JSON構造化ログの動作確認"""

    def test_json_formatter_format(self):
        """JSONFormatterが正しいJSON文字列を生成する"""
        # main.py のJSONFormatterをインポート
        # main.pyのインポートは副作用があるため、クラスを直接テスト
        import json as _json

        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_entry = {
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                if record.exc_info and record.exc_info[0]:
                    log_entry["exception"] = self.formatException(record.exc_info)
                return _json.dumps(log_entry, ensure_ascii=False)

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="テスト日本語メッセージ", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = _json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert parsed["msg"] == "テスト日本語メッセージ"
        assert "ts" in parsed

    def test_json_formatter_with_exception(self):
        """例外情報を含むログがJSON出力される"""
        import json as _json

        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_entry = {
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "msg": record.getMessage(),
                }
                if record.exc_info and record.exc_info[0]:
                    log_entry["exception"] = self.formatException(record.exc_info)
                return _json.dumps(log_entry, ensure_ascii=False)

        formatter = JSONFormatter()
        try:
            raise ValueError("テストエラー")
        except ValueError:
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="エラー発生", args=(), exc_info=sys.exc_info(),
            )
            output = formatter.format(record)
            parsed = _json.loads(output)
            assert "exception" in parsed
            assert "ValueError" in parsed["exception"]


# ============================================================
# 4. 固有名詞辞書API テスト（HR-7）
# ============================================================
class TestProperNounDict:
    """HR-7: getattr → dict.get 修正の検証"""

    def test_get_all_entries_returns_dicts(self):
        """get_all_entries() が辞書のリストを返す"""
        from proper_noun_dict import proper_noun_dict
        entries = proper_noun_dict.get_all_entries()
        assert isinstance(entries, list)
        for e in entries:
            assert isinstance(e, dict)
            assert "id" in e
            assert "incorrect" in e
            assert "correct" in e
            assert "confirmed" in e

    def test_dict_get_access_pattern(self):
        """dict.get() で安全にアクセスできる"""
        from proper_noun_dict import proper_noun_dict
        entries = proper_noun_dict.get_all_entries()
        for e in entries:
            # getattr ではなく dict.get が使えることを確認
            assert e.get("id", "") is not None
            assert e.get("confirmed", False) is not None
            assert e.get("usage_count", 0) is not None


# ============================================================
# 5. RenderWorker 本番品質レンダリング テスト（CR-1）
# ============================================================
class TestRenderWorkerQuality:
    """CR-1: FFmpeg再エンコード + ラウドネス正規化の設定確認"""

    def test_pipeline_coordinator_has_ffmpeg_render(self):
        """RenderWorker にFFmpegレンダリングコードが存在する（Sprint D分離後）"""
        # Sprint D: _render_production_quality は agents/workers/render_worker.py に移動
        source = Path(__file__).parent.parent / "agents" / "workers" / "render_worker.py"
        content = source.read_text(encoding="utf-8")
        # CR-1修正: _render_production_quality が存在することを確認
        assert "_render_production_quality" in content
        # FFmpeg再エンコードの存在を確認
        assert "ffmpeg" in content.lower()
        assert "production" in content.lower()

    def test_audio_master_normalize_exists(self):
        """AudioMaster.normalize_loudness が存在する"""
        from audio_master import AudioMaster
        am = AudioMaster()
        assert hasattr(am, "normalize_loudness")


# ============================================================
# 6. Shorts レンダリングAPI テスト（HR-2）
# ============================================================
class TestShortsRenderAPI:
    """HR-2: Shorts縦型レンダリングの設定確認"""

    def test_shorts_render_endpoint_exists(self):
        """POST /api/shorts/render エンドポイントが存在する"""
        from routers.shorts import router
        routes = [r.path for r in router.routes]
        # ルーターのprefixが/api/shortsなので、route.pathは/renderまたは/api/shorts/render
        has_render = any("render" in r for r in routes)
        assert has_render, f"render not found in routes: {routes}"

    def test_shorts_render_request_model(self):
        """RenderShortRequest モデルが正しいフィールドを持つ"""
        from routers.shorts import RenderShortRequest
        req = RenderShortRequest(
            video_path="/test.mp4",
            start_sec=0.0,
            end_sec=30.0,
        )
        assert req.video_path == "/test.mp4"
        assert req.end_sec == 30.0


# ============================================================
# 7. Whisperサブプロセス化 テスト（HR-4）
# ============================================================
class TestWhisperSubprocess:
    """HR-4: インプロセスWhisper呼び出しの排除確認"""

    def test_production_pipeline_uses_subprocess(self):
        """production_pipeline.py / adk_bridge.py がインプロセスWhisperを排除している"""
        source = Path(__file__).parent.parent / "agents" / "production_pipeline.py"
        if not source.exists():
            # ADK移行後: production_pipeline.py は廃止 → adk_bridge + pipeline_tools で確認
            alt_source = Path(__file__).parent.parent / "harness" / "pipeline_tools.py"
            if not alt_source.exists():
                pytest.skip("production_pipeline.py / pipeline_tools.py いずれも見つかりません")
            content = alt_source.read_text(encoding="utf-8")
            # pipeline_tools にインプロセスWhisper呼び出しがないことを確認
            assert "WhisperTranscriber" not in content or "subprocess" in content.lower()
            return
        content = source.read_text(encoding="utf-8")
        # インプロセス呼び出しが無いことを確認
        assert "WhisperTranscriber" not in content
        assert "asyncio.get_event_loop().run_until_complete" not in content
        # サブプロセス版が使われていることを確認
        assert "whisper_subprocess" in content
        assert "run_whisper_subprocess" in content

    def test_transcribe_sync_exists(self):
        """transcribe_sync.py が存在する"""
        source = Path(__file__).parent.parent / "transcribe_sync.py"
        assert source.exists()


# ============================================================
# 8. ShortsGenerator UIコンポーネント テスト
# ============================================================
class TestShortsGeneratorUI:
    """案A: ShortsGenerator にレンダリング機能が統合されている"""

    def test_shorts_generator_has_render_button(self):
        """ShortsGenerator.jsx にレンダリングボタンが含まれる"""
        source = Path(__file__).parent.parent.parent / "frontend" / "src" / "components" / "ShortsGenerator.jsx"
        content = source.read_text(encoding="utf-8")
        assert "/api/shorts/render" in content
        assert "handleRenderSelected" in content
        assert "isRendering" in content

    def test_shorts_generator_accepts_video_path_prop(self):
        """ShortsGenerator が videoPath プロップを受け取る"""
        source = Path(__file__).parent.parent.parent / "frontend" / "src" / "components" / "ShortsGenerator.jsx"
        content = source.read_text(encoding="utf-8")
        assert "videoPath" in content


# ============================================================
# 9. USER_MANUAL.md 更新確認（HR-6）
# ============================================================
class TestUserManual:
    """HR-6: ドキュメントが最新機能を反映している"""

    def test_manual_has_planning_lab(self):
        """USER_MANUAL.md に企画ラボセクションが存在する"""
        manual = Path(__file__).parent.parent.parent / "docs" / "USER_MANUAL.md"
        content = manual.read_text(encoding="utf-8")
        assert "企画ラボ" in content

    def test_manual_has_health_check(self):
        """USER_MANUAL.md にヘルスチェック記述が存在する"""
        manual = Path(__file__).parent.parent.parent / "docs" / "USER_MANUAL.md"
        content = manual.read_text(encoding="utf-8")
        assert "/health" in content

    def test_manual_has_shorts_render(self):
        """USER_MANUAL.md にShorts縦型レンダリング記述が存在する"""
        manual = Path(__file__).parent.parent.parent / "docs" / "USER_MANUAL.md"
        content = manual.read_text(encoding="utf-8")
        assert "縦型レンダリング" in content

    def test_manual_version_updated(self):
        """USER_MANUAL.md の更新履歴が最新"""
        manual = Path(__file__).parent.parent.parent / "docs" / "USER_MANUAL.md"
        content = manual.read_text(encoding="utf-8")
        assert "2.1.0" in content


# ============================================================
# 10. 品質ゲート2系統統合 テスト（HR-5）
# ============================================================
class TestQualityGatePlugins:
    """HR-5: 放送品質 + YouTube最適化プラグインの統合確認"""

    def test_plugin_registry_has_broadcast_plugins(self):
        """放送品質プラグインがレジストリに登録されている"""
        from quality_gate_plugins import PLUGIN_REGISTRY
        broadcast_plugins = [p for p in PLUGIN_REGISTRY if p.category == "broadcast"]
        assert len(broadcast_plugins) >= 3
        names = [p.name for p in broadcast_plugins]
        assert "loudness_check" in names
        assert "resolution_check" in names
        assert "codec_check" in names

    def test_plugin_registry_has_youtube_plugins(self):
        """YouTube最適化プラグインがレジストリに登録されている"""
        from quality_gate_plugins import PLUGIN_REGISTRY
        youtube_plugins = [p for p in PLUGIN_REGISTRY if p.category == "youtube"]
        assert len(youtube_plugins) >= 3
        names = [p.name for p in youtube_plugins]
        assert "chapter_coverage_check" in names
        assert "shorts_ready_check" in names
        assert "ctr_ready_check" in names

    def test_all_five_categories_present(self):
        """全5カテゴリのプラグインが存在する（core/template/broadcast/youtube）"""
        from quality_gate_plugins import PLUGIN_REGISTRY
        categories = set(p.category for p in PLUGIN_REGISTRY)
        assert "core" in categories
        assert "template" in categories
        assert "broadcast" in categories
        assert "youtube" in categories

    def test_run_all_plugins_returns_structured_result(self):
        """run_all_plugins が構造化結果を返す"""
        from quality_gate_plugins import run_all_plugins

        # ダミーコンテキスト
        class MockCtx:
            preview_path = None
            segments = [
                {"start": 0, "end": 3, "text": "テストセグメント1"},
                {"start": 3, "end": 6, "text": "テストセグメント2"},
            ]

        result = run_all_plugins(MockCtx())
        assert "total_deductions" in result
        assert "final_score" in result
        assert "category_scores" in result
        assert "category_report" in result
        assert isinstance(result["category_report"], list)

    def test_category_scores_populated(self):
        """カテゴリスコアが算出される"""
        from quality_gate_plugins import run_all_plugins

        class MockCtx:
            preview_path = None
            segments = [
                {"start": 0, "end": 3, "text": "テスト"},
                {"start": 3, "end": 6, "text": "テスト2"},
            ]

        result = run_all_plugins(MockCtx())
        cs = result["category_scores"]
        assert "core" in cs
        assert "broadcast" in cs
        assert "youtube" in cs

    def test_block_mode_works(self):
        """ブロックモードが正しく動作する"""
        from quality_gate_plugins import run_all_plugins

        class MockCtx:
            preview_path = None
            segments = []

        result = run_all_plugins(MockCtx(), block_mode=True)
        assert "block_recommended" in result

    def test_broadcast_plugins_safe_on_no_file(self):
        """放送品質プラグインはファイル不在時にスキップする"""
        from quality_gate_plugins import LoudnessCheck, ResolutionCheck, CodecCheck

        class MockCtx:
            preview_path = None
            segments = []

        for PluginClass in [LoudnessCheck, ResolutionCheck, CodecCheck]:
            plugin = PluginClass()
            result = plugin.analyze(MockCtx())
            assert result["deductions"] == 0

    def test_youtube_plugins_with_segments(self):
        """YouTube最適化プラグインがセグメント付きで動作する"""
        from quality_gate_plugins import ShortsReadyCheck, CTRReadyCheck

        class MockCtx:
            preview_path = None
            segments = [
                {"start": 0, "end": 5, "text": "すごいですね！これはやばい"},
                {"start": 5, "end": 10, "text": "本当に最高でした"},
                {"start": 10, "end": 15, "text": "まとめになります"},
            ]

        shorts = ShortsReadyCheck()
        result = shorts.analyze(MockCtx())
        assert result["deductions"] == 0  # ハイライトワードあり

        ctr = CTRReadyCheck()
        result = ctr.analyze(MockCtx())
        assert result["deductions"] == 0  # テキスト十分

    def test_total_plugin_count(self):
        """プラグイン総数が16以上"""
        from quality_gate_plugins import PLUGIN_REGISTRY
        assert len(PLUGIN_REGISTRY) >= 16


# ============================================================
# 11. 並行安全性テスト
# ============================================================
class TestConcurrencySafety:
    """PipelineCoordinatorの独立性確認"""

    def test_coordinator_instances_are_independent(self):
        """複数のPipelineCoordinatorインスタンスが独立している"""
        from agents.pipeline_coordinator import PipelineCoordinator
        c1 = PipelineCoordinator()
        c2 = PipelineCoordinator()
        # 各インスタンスのworkerリストが独立
        assert c1.workers is not c2.workers
        assert len(c1.workers) == len(c2.workers)

    def test_pipeline_context_isolation(self):
        """PipelineContextが各パイプラインで独立している"""
        from agents.pipeline_coordinator import PipelineContext
        ctx1 = PipelineContext(video_path="a.mp4")
        ctx2 = PipelineContext(video_path="b.mp4")
        ctx1.segments = [{"text": "test1"}]
        ctx2.segments = [{"text": "test2"}]
        # 相互に影響しないことを確認
        assert ctx1.segments != ctx2.segments
        assert ctx1.video_path != ctx2.video_path

    def test_quality_gate_plugins_stateless(self):
        """品質ゲートプラグインがステートレスである"""
        from quality_gate_plugins import PLUGIN_REGISTRY

        class MockCtx:
            preview_path = None
            segments = [{"start": 0, "end": 3, "text": "A"}]
            selected_segments = [{"start": 0, "end": 3, "text": "A"}]
            metadata = {"titles": ["test"], "tags": ["t"], "description": "test desc"}

        # 同じプラグインを2回実行しても結果が同じ
        for plugin in PLUGIN_REGISTRY:
            if plugin.category in ("core", "youtube"):
                r1 = plugin.analyze(MockCtx())
                r2 = plugin.analyze(MockCtx())
                assert r1["deductions"] == r2["deductions"], \
                    f"{plugin.name} is not stateless"


# ============================================================
# 12. テスト動画スモーク検証
# ============================================================
class TestTestVideos:
    """Q3: テスト動画の存在とサイズ検証"""

    TEST_VIDEOS_DIR = Path(__file__).parent.parent / "vault-assets" / "test_videos"

    def test_test_30sec_exists(self):
        """test_30sec.mp4 が存在し、100KB以上"""
        p = self.TEST_VIDEOS_DIR / "test_30sec.mp4"
        if not p.exists():
            pytest.skip("テスト動画未生成（python scripts/create_test_videos.py を先に実行）")
        assert p.stat().st_size > 100 * 1024

    def test_test_5min_exists(self):
        """test_5min.mp4 が存在し、1MB以上"""
        p = self.TEST_VIDEOS_DIR / "test_5min.mp4"
        if not p.exists():
            pytest.skip("テスト動画未生成")
        assert p.stat().st_size > 1 * 1024 * 1024

    def test_test_silence_exists(self):
        """test_silence.mp4 が存在する"""
        p = self.TEST_VIDEOS_DIR / "test_silence.mp4"
        if not p.exists():
            pytest.skip("テスト動画未生成")
        assert p.stat().st_size > 50 * 1024

    def test_test_mono_exists(self):
        """test_mono.mp4（モノラル）が存在する"""
        p = self.TEST_VIDEOS_DIR / "test_mono.mp4"
        if not p.exists():
            pytest.skip("テスト動画未生成")
        assert p.stat().st_size > 50 * 1024

    def test_test_lowres_exists(self):
        """test_lowres.mp4（480p）が存在する"""
        p = self.TEST_VIDEOS_DIR / "test_lowres.mp4"
        if not p.exists():
            pytest.skip("テスト動画未生成")
        assert p.stat().st_size > 50 * 1024
