"""
M2.8 Soul Narrative 自動更新テスト (T-072〜T-075)

MASTER v3.6 §5.2 対応:
  T-072: _trigger_dream_learning の try-except 修正検証
  T-073: パイプライン完了後に evolution_log (knowledge JSON) 更新確認
  T-074: エントリに session_id / 日時 / スコア含む構造検証
  T-075: 哲学エントリが累積的であることの確認 (video_processor._record_soul_narrative)

合計: 4テスト
"""

import sys
import json
import pytest
import time as _time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


class TestM28SoulNarrative:
    """M2.8 Soul Narrative 自動更新テスト"""

    # ── T-072: _trigger_dream_learning の try-except ──

    @pytest.mark.asyncio
    async def test_t072_dream_learning_exception_safe(self):
        """T-072: _trigger_dream_learning は ImportError / 例外で leak しない + ログ出力"""
        from agents.pipeline_coordinator import PipelineCoordinator
        from agents.pipeline_types import PipelineContext

        coord = PipelineCoordinator()
        ctx = PipelineContext(
            video_path="/fake/video.mp4",
            target_minutes=20,
            session_id="test-072",
        )
        ctx.segments = [{"text": "テスト", "start": 0, "end": 3}]
        ctx.selected_segments = ctx.segments
        ctx.quality_score = 85
        ctx.stage_results = []

        # Case 1: ImportError (dream_engine モジュールなし)
        with patch.dict(sys.modules, {"agents.dream_engine": None}):
            # 例外が発生せずに正常終了すること
            await coord._trigger_dream_learning(ctx)

        # Case 2: dream_engine.should_dream が例外を投げる
        mock_de = MagicMock()
        mock_de.increment_session_count = MagicMock(side_effect=RuntimeError("DB接続エラー"))
        mock_module = MagicMock(dream_engine=mock_de)

        with patch.dict(sys.modules, {"agents.dream_engine": mock_module}):
            # RuntimeError が leak しないこと
            await coord._trigger_dream_learning(ctx)

    # ── T-073: パイプライン完了後に knowledge JSON 生成 ──

    @pytest.mark.asyncio
    async def test_t073_knowledge_json_created(self, tmp_path):
        """T-073: _trigger_dream_learning が knowledge JSON ファイルを生成する"""
        from agents.pipeline_coordinator import PipelineCoordinator
        from agents.pipeline_types import PipelineContext, StageResult

        coord = PipelineCoordinator()
        ctx = PipelineContext(
            video_path="/fake/video.mp4",
            target_minutes=20,
            session_id="test-073",
        )
        ctx.segments = [{"text": "テスト", "start": 0, "end": 3}]
        ctx.selected_segments = ctx.segments
        ctx.quality_score = 92
        ctx.stage_results = [
            StageResult(
                stage_name="AI校閲", success=True,
                detail="5件修正", duration_seconds=2.5,
                data={"total": 5},
            ),
        ]

        # dream_engine import を成功させつつ、知識ファイルの出力先を tmp_path に差し替え
        mock_de = MagicMock()
        mock_de.increment_session_count = MagicMock()
        mock_de.should_dream = AsyncMock(return_value=False)
        mock_module = MagicMock(dream_engine=mock_de)

        knowledge_dir = tmp_path / "logs" / "pipeline_knowledge"

        with patch.dict(sys.modules, {"agents.dream_engine": mock_module}), \
             patch("agents.pipeline_coordinator.Path.__truediv__",
                   side_effect=lambda self, other: (
                       knowledge_dir if other == "pipeline_knowledge"
                       else tmp_path / other
                   )) if False else \
             patch.object(
                 Path, "__new__", wraps=Path.__new__
             ) if False else \
             patch(
                 "agents.pipeline_coordinator.Path",
                 wraps=Path
             ) if False else \
             _noop_ctx():

            # __file__ 基準のパスを差し替える
            with patch("agents.pipeline_coordinator.Path") as MockPath:
                # Path(__file__).parent / "logs" / "pipeline_knowledge" を tmp_path に誘導
                mock_file_parent = MagicMock()
                mock_file_parent.__truediv__ = lambda self, x: tmp_path / x
                MockPath.return_value.parent = mock_file_parent
                MockPath.side_effect = lambda x: Path(x) if isinstance(x, str) and x.startswith("/") else MagicMock(parent=mock_file_parent)

                # 直接 knowledge_path を差し替え
                # 最もシンプルな方法: 関数自体の動作を検証するため、
                # logs/pipeline_knowledge ディレクトリを tmp_path 下に用意
                pass

        # よりシンプルなアプローチ: 関数の内部ロジックを直接テスト
        # _trigger_dream_learning の L764-771 が knowledge JSON を書き出す
        # tmp_path を使ってそのパスを上書き
        knowledge_base = tmp_path / "logs" / "pipeline_knowledge"
        knowledge_base.mkdir(parents=True, exist_ok=True)

        # pipeline_coordinator.py L764 の Path(__file__).parent を tmp_path に差し替え
        import agents.pipeline_coordinator as pc_module

        original_path_file = pc_module.__file__
        try:
            # __file__ 属性を差し替えて knowledge_path を tmp_path 配下にする
            # L764: knowledge_path = Path(__file__).parent / "logs" / "pipeline_knowledge"
            pc_module.__file__ = str(tmp_path / "pipeline_coordinator.py")

            with patch.dict(sys.modules, {"agents.dream_engine": mock_module}):
                await coord._trigger_dream_learning(ctx)

            # knowledge JSON が生成されたことを確認
            json_files = list(knowledge_base.glob("run_*.json"))
            assert len(json_files) >= 1, f"knowledge JSON 未生成: {list(knowledge_base.iterdir())}"

            # JSON の内容を検証
            with open(json_files[0], "r", encoding="utf-8") as f:
                knowledge = json.load(f)

            assert knowledge["type"] == "pipeline_completion"
            assert knowledge["quality_score"] == 92
            assert knowledge["segments_total"] == 1
            assert knowledge["video"] == "video.mp4"

        finally:
            pc_module.__file__ = original_path_file

    # ── T-074: エントリに session_id / 日時 / スコア含む ──

    @pytest.mark.asyncio
    async def test_t074_knowledge_entry_structure(self, tmp_path):
        """T-074: knowledge JSON エントリに必須フィールドが含まれる"""
        from agents.pipeline_coordinator import PipelineCoordinator
        from agents.pipeline_types import PipelineContext, StageResult

        coord = PipelineCoordinator()
        ctx = PipelineContext(
            video_path="/fake/my_video.mp4",
            target_minutes=15,
            session_id="session-074-abc",
        )
        ctx.segments = [
            {"text": "テスト1", "start": 0, "end": 5},
            {"text": "テスト2", "start": 5, "end": 10},
        ]
        ctx.selected_segments = [ctx.segments[0]]
        ctx.quality_score = 88
        ctx.stage_results = [
            StageResult(
                stage_name="文字起こし", success=True,
                detail="2 segments", duration_seconds=10.5,
                data={"segment_count": 2},
            ),
            StageResult(
                stage_name="AI校閲", success=True,
                detail="3件修正", duration_seconds=3.0,
                data={"total": 3},
                retries=1,
            ),
        ]

        knowledge_base = tmp_path / "logs" / "pipeline_knowledge"
        knowledge_base.mkdir(parents=True, exist_ok=True)

        import agents.pipeline_coordinator as pc_module
        mock_de = MagicMock()
        mock_de.increment_session_count = MagicMock()
        mock_de.should_dream = AsyncMock(return_value=False)
        mock_module = MagicMock(dream_engine=mock_de)

        original_file = pc_module.__file__
        try:
            pc_module.__file__ = str(tmp_path / "pipeline_coordinator.py")

            with patch.dict(sys.modules, {"agents.dream_engine": mock_module}):
                await coord._trigger_dream_learning(ctx)

            json_files = list(knowledge_base.glob("run_*.json"))
            assert len(json_files) >= 1

            with open(json_files[0], "r", encoding="utf-8") as f:
                k = json.load(f)

            # 必須フィールド検証
            assert "timestamp" in k, "timestamp フィールドが欠損"
            assert "type" in k and k["type"] == "pipeline_completion"
            assert "video" in k and k["video"] == "my_video.mp4"
            assert "segments_total" in k and k["segments_total"] == 2
            assert "segments_selected" in k and k["segments_selected"] == 1
            assert "quality_score" in k and k["quality_score"] == 88
            assert "stage_durations" in k
            assert "文字起こし" in k["stage_durations"]
            assert k["stage_durations"]["文字起こし"] == 10.5
            assert "total_corrections" in k and k["total_corrections"] == 3
            assert "retries_used" in k and k["retries_used"] == 1

            # タイムスタンプが ISO 形式であること
            datetime.fromisoformat(k["timestamp"])

        finally:
            pc_module.__file__ = original_file

    # ── T-075: 哲学エントリの累積性 (video_processor) ──

    def test_t075_evolution_log_accumulates(self, tmp_path):
        """T-075: _record_soul_narrative は evolution_log エントリを累積的に追加する"""
        from video_processor import VideoProcessor, MOOD_SETTINGS

        proc = VideoProcessor(output_dir=str(tmp_path / "output"))

        # evolution_log.json を tmp_path/branding 配下に用意
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir()
        evo_log_path = branding_dir / "evolution_log.json"

        initial_log = {
            "entries": [
                {"timestamp": 1000, "type": "initial", "summary": "初期エントリ"}
            ],
            "philosophies": ["品質第一"],
        }
        evo_log_path.write_text(
            json.dumps(initial_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        settings = MOOD_SETTINGS["elegant"]

        # _record_soul_narrative の Path(__file__).parent を差し替え
        import video_processor as vp_module
        original_file = vp_module.__file__
        try:
            vp_module.__file__ = str(tmp_path / "video_processor.py")

            # 1回目の記録
            proc._record_soul_narrative("task-001", "output1", settings, 3)

            with open(evo_log_path, "r", encoding="utf-8") as f:
                log1 = json.load(f)
            assert len(log1["entries"]) == 2, "エントリが追加されていない"
            assert log1["entries"][0]["type"] == "initial"  # 既存エントリ保持
            assert log1["entries"][1]["type"] == "video_production"
            assert log1["entries"][1]["task_id"] == "task-001"

            # 2回目の記録 → 累積的に追加
            proc._record_soul_narrative("task-002", "output2", settings, 5)

            with open(evo_log_path, "r", encoding="utf-8") as f:
                log2 = json.load(f)
            assert len(log2["entries"]) == 3, "2回目のエントリが追加されていない"
            assert log2["entries"][2]["task_id"] == "task-002"

            # philosophies が保持されていること
            assert "品質第一" in log2["philosophies"]

        finally:
            vp_module.__file__ = original_file


# ── ヘルパー ──

import contextlib

@contextlib.contextmanager
def _noop_ctx():
    """no-op コンテキストマネージャ"""
    yield
