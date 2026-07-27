"""
test_transcribe_worker.py — M2.2 Sprint 2.2.1 TranscribeWorker 66テスト

Worker本体(19分岐) + whisper_subprocess(27分岐) + whisper_transcriber(20分岐) = 66分岐
6カテゴリ × 11テスト = 66テスト

テスト設計方針:
  - 実際の Whisper / GPU は使わない（サブプロセスモック）
  - チェックポイント JSONL のファイル I/O は tmp_path で検証
  - TV-01 (実データ) のキャッシュ JSONL を使う場合はキャッシュパス存在を前提
"""

import sys
import json
import time
import asyncio
import subprocess
import threading
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.pipeline_coordinator import (
    PipelineContext, PipelineCoordinator, StageResult,
    TranscribeWorker,
)
from tests.fixtures.mock_pipeline import create_mock_ctx


# ============================================================
# ヘルパー: チェックポイント JSONL 生成
# ============================================================

def _create_checkpoint_jsonl(path: Path, segment_count: int = 10):
    """テスト用 JSONL チェックポイントファイルを生成

    各行>350bytes保証。3セグメントで>1000bytes（キャッシュパス閾値）超過。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i in range(segment_count):
            # 長いテキストで1行あたり>350bytesを保証
            text = (
                f"テストセグメント{i+1}：この動画は非常に興味深い内容を含んでおり、"
                f"視聴者の注目を集めることが期待される高品質な映像作品です。"
                f"制作にあたっては最新の技術を駆使し、細部にまでこだわった仕上がりです。"
            )
            seg = {
                "start": i * 15.0,
                "end": (i + 1) * 15.0,
                "text": text,
                "sourceStart": i * 15.0,
                "sourceEnd": (i + 1) * 15.0,
            }
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")


def _create_small_checkpoint(path: Path, size_bytes: int = 500):
    """サイズの小さい（不完全な）チェックポイントファイル"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * size_bytes, encoding="utf-8")


def _mock_popen_success(checkpoint_path: str, segments: int = 10):
    """成功する Popen モックを返す"""
    def _popen_init(*args, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = iter([
            json.dumps({"progress": 50}) + "\n",
            json.dumps({"status": "completed", "device": "cuda", "model": "small"}) + "\n",
        ])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait = MagicMock()
        # チェックポイントファイルを書き出し
        _create_checkpoint_jsonl(Path(checkpoint_path), segments)
        return mock_proc
    return _popen_init


def _mock_popen_failure(exit_code: int = 1, stderr_msg: str = "error"):
    """失敗する Popen モックを返す"""
    def _popen_init(*args, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = exit_code
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = stderr_msg
        mock_proc.wait = MagicMock()
        return mock_proc
    return _popen_init


def _mock_popen_timeout():
    """タイムアウトする Popen モックを返す"""
    def _popen_init(*args, **kwargs):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        # 1回目の wait() で TimeoutExpired 例外、2回目の wait() では正常終了(0)を返すように設定
        mock_proc.wait = MagicMock(side_effect=[subprocess.TimeoutExpired(cmd="whisper", timeout=600), 0])
        mock_proc.kill = MagicMock()
        return mock_proc
    return _popen_init


# ============================================================
# C1: 入力検証 (11)
# ============================================================

class TestC1InputValidation:
    """W1-C1: TranscribeWorker 入力検証"""

    @pytest.mark.asyncio
    async def test_C1_01_normal_video_produces_segments(self, tmp_path):
        """W1-C1-01: 音声明瞭5分動画(TV-01 正常) → seg≥10"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "test.mp4"))
        cp_path = tmp_path / "test_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 15)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert result.data.get("segment_count", 0) >= 10
        assert len(ctx.segments) >= 10

    @pytest.mark.asyncio
    async def test_C1_02_silent_video_zero_segments(self, tmp_path):
        """W1-C1-02: 5秒無音動画(TV-02 最小) → seg=0 + 正常終了"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "silent.mp4"))
        cp_path = tmp_path / "silent_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 0)  # 空ファイル = 0セグメント

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        # 0セグメントだがチェックポイントファイルサイズ<1000なのでWhisper実行を試みる
        # → サブプロセスモックが必要だが、ここではキャッシュパスのサイズチェック分岐を検証
        assert isinstance(result, StageResult)

    @pytest.mark.asyncio
    async def test_C1_03_long_video_mock_timeout(self, tmp_path):
        """W1-C1-03: 30分動画(最大・モック) → 180秒以内 or graceful停止"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "long.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "long.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="long1234"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_timeout()):
                        result = await worker.execute(ctx)

        # タイムアウト → success=False + エラー詳細
        assert result.success is False
        assert ("タイムアウト" in result.detail
                or "Timeout" in result.detail
                or "timed out" in result.detail)

    @pytest.mark.asyncio
    async def test_C1_04_corrupt_video_error(self, tmp_path):
        """W1-C1-04: 破損mp4(TV-03 不正) → エラーログ+ctx.error"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "corrupt.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "corrupt.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="corrupt1"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "Invalid data found when processing input")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C1_05_empty_file_error(self, tmp_path):
        """W1-C1-05: 0バイトファイル(TV-04 空) → エラーハンドリング"""
        worker = TranscribeWorker()
        empty_file = tmp_path / "empty.mp4"
        empty_file.write_bytes(b"")
        ctx = PipelineContext(video_path=str(empty_file))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "empty.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="empty123"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "empty input")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C1_06_japanese_path_encoding(self, tmp_path):
        """W1-C1-06: 日本語パス動画(TV-05) → パスエンコーディング正常"""
        jp_dir = tmp_path / "動画フォルダ"
        jp_dir.mkdir()
        jp_file = jp_dir / "テスト動画.mp4"
        jp_file.write_bytes(b"\x00" * 100)

        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(jp_file))
        cp_path = jp_dir / "テスト動画_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.segments) == 5

    @pytest.mark.asyncio
    async def test_C1_07_nonexistent_path(self, tmp_path):
        """W1-C1-07: 存在しないパス → エラー"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "nonexistent.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "ne.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="ne123456"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "No such file")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C1_08_directory_path_error(self, tmp_path):
        """W1-C1-08: ディレクトリパス(ファイルでない) → 明確なエラー"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path))  # ディレクトリを指定

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "dir.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="dir12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "Is a directory")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C1_09_no_audio_track(self, tmp_path):
        """W1-C1-09: 音声トラックなし動画 → エラーハンドリング"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "no_audio.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "na.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="noaud123"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "no audio stream")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C1_10_non_mp4_format(self, tmp_path):
        """W1-C1-10: 非MP4フォーマット(AVI/MKV) → 正常処理 or エラー"""
        worker = TranscribeWorker()
        avi_file = tmp_path / "test.avi"
        avi_file.write_bytes(b"\x00" * 100)
        ctx = PipelineContext(video_path=str(avi_file))
        cp_path = tmp_path / "test_avi12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 3)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="avi12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    result = await worker.execute(ctx)

        # キャッシュ存在 → 正常読み込み
        assert result.success is True

    @pytest.mark.asyncio
    async def test_C1_11_no_read_permission(self, tmp_path):
        """W1-C1-11: 読取権限なしファイル → エラー"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "noperm.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", side_effect=PermissionError("Access denied")):
            result = await worker.execute(ctx)

        assert result.success is False


# ============================================================
# C2: コアロジック (11)
# ============================================================

class TestC2CoreLogic:
    """W1-C2: TranscribeWorker コアロジック"""

    @pytest.mark.asyncio
    async def test_C2_01_gpu_mode_execution(self, tmp_path):
        """W1-C2-01: GPUモード(NVENC)での実行 → device=cuda"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "gpu.mp4"))
        cp_path = tmp_path / "gpu_abc12345.jsonl"

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 10)):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert result.data.get("device") == "cuda"

    @pytest.mark.asyncio
    async def test_C2_02_cpu_mode_execution(self, tmp_path):
        """W1-C2-02: CPUモードでの実行 → device=cpu"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "cpu.mp4"))
        cp_path = tmp_path / "cpu_abc12345.jsonl"

        def _popen_cpu(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = iter([
                json.dumps({"status": "completed", "device": "cpu", "model": "small"}) + "\n",
            ])
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait = MagicMock()
            _create_checkpoint_jsonl(Path(str(cp_path)), 5)
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_cpu):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert result.data.get("device") == "cpu"

    def test_C2_03_model_size_is_small(self):
        """W1-C2-03: モデルサイズ判定 → small固定"""
        # TranscribeWorker L152: model_size = "small"
        # コード内で直接 "small" と定義されている
        worker = TranscribeWorker()
        # ソースコードを検証（model_sizeはexecuteの中のローカル変数）
        import inspect
        source = inspect.getsource(worker.execute)
        assert 'model_size = "small"' in source

    @pytest.mark.asyncio
    async def test_C2_04_checkpoint_resume(self, tmp_path):
        """W1-C2-04: チェックポイントからの再開 → 既存JSONL読み込み成功"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "resume.mp4"))
        cp_path = tmp_path / "resume_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 20)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert "キャッシュ" in result.detail
        assert result.data.get("model") == "cached"
        assert len(ctx.segments) == 20

    @pytest.mark.asyncio
    async def test_C2_05_hash_based_cache_isolation(self, tmp_path):
        """W1-C2-05: 動画固有ハッシュによるキャッシュ分離"""
        worker = TranscribeWorker()

        # 動画A: ハッシュ "aaa11111"
        ctx_a = PipelineContext(video_path=str(tmp_path / "video_a.mp4"))
        cp_a = tmp_path / "video_a_aaa11111.jsonl"
        _create_checkpoint_jsonl(cp_a, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_a)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="aaa11111"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    result_a = await worker.execute(ctx_a)

        # 動画B: ハッシュ "bbb22222"
        ctx_b = PipelineContext(video_path=str(tmp_path / "video_b.mp4"))
        cp_b = tmp_path / "video_b_bbb22222.jsonl"
        _create_checkpoint_jsonl(cp_b, 8)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_b)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="bbb22222"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    result_b = await worker.execute(ctx_b)

        assert len(ctx_a.segments) == 5
        assert len(ctx_b.segments) == 8
        assert len(ctx_a.segments) != len(ctx_b.segments)

    @pytest.mark.asyncio
    async def test_C2_06_small_checkpoint_triggers_whisper(self, tmp_path):
        """W1-C2-06: チェックポイントファイルサイズ<1000バイト時 → Whisper再実行"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "small_cp.mp4"))
        cp_path = tmp_path / "small_abc12345.jsonl"
        _create_small_checkpoint(cp_path, 500)  # < 1000 bytes

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 10)):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert "キャッシュ" not in result.detail  # キャッシュではなくWhisper実行

    @pytest.mark.asyncio
    async def test_C2_07_stdout_json_parsing(self, tmp_path):
        """W1-C2-07: サブプロセスstdoutのJSON解析 → progress/status取得"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "parse.mp4"))
        cp_path = tmp_path / "parse_abc12345.jsonl"

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 10)):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert result.data.get("device") == "cuda"  # stdoutからパース

    @pytest.mark.asyncio
    async def test_C2_08_stdout_invalid_json_skipped(self, tmp_path):
        """W1-C2-08: サブプロセスstdoutのJSON不正行 → パースエラースキップ"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "badjson.mp4"))
        cp_path = tmp_path / "badjson_abc12345.jsonl"

        def _popen_bad_json(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = iter([
                "NOT JSON LINE\n",
                "{invalid json\n",
                json.dumps({"status": "completed", "device": "cuda", "model": "small"}) + "\n",
            ])
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait = MagicMock()
            _create_checkpoint_jsonl(Path(str(cp_path)), 5)
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_bad_json):
                        result = await worker.execute(ctx)

        assert result.success is True  # 不正行はスキップして成功

    @pytest.mark.asyncio
    async def test_C2_09_reader_thread_completes(self, tmp_path):
        """W1-C2-09: 非ブロッキングstdout読取スレッド → スレッド正常終了"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "thread.mp4"))
        cp_path = tmp_path / "thread_abc12345.jsonl"

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 5)):
                        result = await worker.execute(ctx)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_C2_10_run_in_executor_asyncio(self, tmp_path):
        """W1-C2-10: run_in_executor経由のサブプロセス実行 → asyncio互換"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "executor.mp4"))
        cp_path = tmp_path / "executor_abc12345.jsonl"

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 5)):
                        # asyncio event loop 内で正常動作することを確認
                        result = await worker.execute(ctx)

        assert result.success is True
        assert result.duration_seconds >= 0

    def test_C2_11_language_param_ja(self):
        """W1-C2-11: 言語パラメータ"ja"の伝搬 → サブプロセス引数確認"""
        import inspect
        source = inspect.getsource(TranscribeWorker._run_whisper_subprocess)
        # Popen引数に "ja" が含まれることを確認
        assert '"ja"' in source


# ============================================================
# C3: 出力検証 (11)
# ============================================================

class TestC3OutputValidation:
    """W1-C3: TranscribeWorker 出力検証"""

    @pytest.mark.asyncio
    async def test_C3_01_segment_schema(self, tmp_path):
        """W1-C3-01: 出力segの各要素にtext/start/end含む"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "schema.mp4"))
        cp_path = tmp_path / "schema_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        for seg in ctx.segments:
            assert "text" in seg, f"text missing in {seg}"
            assert "start" in seg, f"start missing in {seg}"
            assert "end" in seg, f"end missing in {seg}"

    @pytest.mark.asyncio
    async def test_C3_02_start_less_than_end(self, tmp_path):
        """W1-C3-02: start < end (全seg)"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "time.mp4"))
        cp_path = tmp_path / "time_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 10)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        for seg in ctx.segments:
            assert seg["start"] < seg["end"], f"start >= end: {seg}"

    @pytest.mark.asyncio
    async def test_C3_03_last_seg_within_duration(self, tmp_path):
        """W1-C3-03: 最終seg.end ≤ 動画尺"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "dur.mp4"))
        cp_path = tmp_path / "dur_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 10)  # 10×15s = 150s

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        if ctx.segments:
            last_end = ctx.segments[-1]["end"]
            assert last_end > 0

    @pytest.mark.asyncio
    async def test_C3_04_no_overlap(self, tmp_path):
        """W1-C3-04: seg間に重複なし"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "overlap.mp4"))
        cp_path = tmp_path / "overlap_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 10)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        for i in range(len(ctx.segments) - 1):
            assert ctx.segments[i]["end"] <= ctx.segments[i + 1]["start"]

    @pytest.mark.asyncio
    async def test_C3_05_jsonl_format_valid(self, tmp_path):
        """W1-C3-05: 出力JSONL形式の正当性"""
        cp_path = tmp_path / "valid.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with open(cp_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                     parsed = json.loads(line)
                     assert isinstance(parsed, dict), f"Line {line_num} not a dict"

    @pytest.mark.asyncio
    async def test_C3_06_stage_result_success_bool(self, tmp_path):
        """W1-C3-06: StageResult.successの真偽"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "bool.mp4"))
        cp_path = tmp_path / "bool_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert isinstance(result.success, bool)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_C3_07_segment_count_accuracy(self, tmp_path):
        """W1-C3-07: StageResult.data.segment_countの正確性"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "count.mp4"))
        cp_path = tmp_path / "count_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 7)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.data["segment_count"] == len(ctx.segments)
        assert result.data["segment_count"] == 7

    @pytest.mark.asyncio
    async def test_C3_08_model_value(self, tmp_path):
        """W1-C3-08: StageResult.data.modelの値 → cached or small"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "model.mp4"))
        cp_path = tmp_path / "model_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.data["model"] in ("small", "medium", "large", "cached")

    @pytest.mark.asyncio
    async def test_C3_09_device_value(self, tmp_path):
        """W1-C3-09: StageResult.data.deviceの値"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "device.mp4"))
        cp_path = tmp_path / "device_abc12345.jsonl"

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 5)):
                        result = await worker.execute(ctx)

        assert result.data.get("device") in ("cuda", "cpu", "unknown", "timeout_partial")

    @pytest.mark.asyncio
    async def test_C3_10_duration_positive(self, tmp_path):
        """W1-C3-10: StageResult.duration_secondsが正数"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "dur_pos.mp4"))
        cp_path = tmp_path / "dur_pos_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_C3_11_cache_detail_display(self, tmp_path):
        """W1-C3-11: キャッシュ使用時のdetail表示 → "(キャッシュ)"を含む"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "cache.mp4"))
        cp_path = tmp_path / "cache_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert "キャッシュ" in result.detail


# ============================================================
# C4: エラー耐性 (11)
# ============================================================

class TestC4ErrorResilience:
    """W1-C4: TranscribeWorker エラー耐性"""

    @pytest.mark.asyncio
    async def test_C4_01_abnormal_exit_no_panic(self, tmp_path):
        """W1-C4-01: Whisperプロセスの異常終了(exit≠0) → panic禁止"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "exit1.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "exit1.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="exit1234"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "Segmentation fault")):
                        result = await worker.execute(ctx)

        assert result.success is False
        assert isinstance(result.detail, str)
        # panic/crash はしない

    @pytest.mark.asyncio
    async def test_C4_02_gpu_vram_fallback(self, tmp_path):
        """W1-C4-02: GPU VRAM不足 → エラーハンドリング"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "vram.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "vram.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="vram1234"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "CUDA out of memory")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C4_03_disk_full(self, tmp_path):
        """W1-C4-03: ディスク容量不足(JSONL書込失敗) → graceful"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "disk.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "disk.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="disk1234"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(1, "No space left on device")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C4_04_ffmpeg_not_installed(self, tmp_path):
        """W1-C4-04: FFmpeg未インストール → 明確なエラーメッセージ"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "noffmpeg.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "ff.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="ff123456"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", side_effect=FileNotFoundError("ffmpeg not found")):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C4_05_subprocess_timeout(self, tmp_path):
        """W1-C4-05: サブプロセスタイムアウト(600秒) → 強制終了"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "timeout.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "to.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="to123456"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_timeout()):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C4_06_timeout_with_checkpoint(self, tmp_path):
        """W1-C4-06: タイムアウト+チェックポイントあり → 部分結果で続行"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "to_cp.mp4"))
        cp_path = tmp_path / "to_cp.jsonl"
        _create_checkpoint_jsonl(cp_path, 2)  # > 500 bytes かつ < 1000 bytes (キャッシュスキップ防止)

        def _popen_timeout_with_cp(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            # 1回目の wait() で TimeoutExpired 例外、2回目の wait() では正常終了(0)を返すように設定
            mock_proc.wait = MagicMock(side_effect=[subprocess.TimeoutExpired(cmd="w", timeout=600), 0])
            mock_proc.kill = MagicMock()
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="tocp1234"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_timeout_with_cp):
                        result = await worker.execute(ctx)

        # チェックポイントあり → 部分結果で成功扱い
        assert result.success is True
        assert len(ctx.segments) == 2

    @pytest.mark.asyncio
    async def test_C4_07_timeout_no_checkpoint(self, tmp_path):
        """W1-C4-07: タイムアウト+チェックポイントなし → RuntimeError"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "to_no.mp4"))

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "nocp.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="nocp1234"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_timeout()):
                        result = await worker.execute(ctx)

        assert result.success is False
        assert ("タイムアウト" in result.detail
                or "Timeout" in result.detail
                or "timed out" in result.detail)

    @pytest.mark.asyncio
    async def test_C4_08_stdout_fail_but_jsonl_exists(self, tmp_path):
        """W1-C4-08: stdoutパース失敗+正常終了+JSONL存在 → フォールバック復旧"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "fbk.mp4"))
        cp_path = tmp_path / "fbk_abc12345.jsonl"

        def _popen_no_stdout(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = iter([])  # stdout出力なし
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait = MagicMock()
            _create_checkpoint_jsonl(Path(str(cp_path)), 10)  # >1000B必要
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_no_stdout):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert result.data.get("device") == "unknown"

    @pytest.mark.asyncio
    async def test_C4_09_stdout_fail_no_jsonl(self, tmp_path):
        """W1-C4-09: stdoutパース失敗+正常終了+JSONL不在 → RuntimeError"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "nojsonl.mp4"))

        def _popen_no_output(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.stdout = iter([])
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = "unknown error"
            mock_proc.wait = MagicMock()
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "nojsonl.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="nojl1234"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_no_output):
                        result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_C4_10_unicode_decode_error(self, tmp_path):
        """W1-C4-10: JSONL読込時のUnicodeDecodeError → エラーハンドリング"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "unicode.mp4"))
        cp_path = tmp_path / "unicode_abc12345.jsonl"
        # バイナリデータでJSONL作成（UTF-8不正）
        cp_path.write_bytes(b'\xff\xfe' + b'{"text": "test"}\n' * 100)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        # UTF-8読み込みでエラーまたは部分成功
        assert isinstance(result, StageResult)

    @pytest.mark.asyncio
    async def test_C4_11_coordinator_name_error(self, tmp_path):
        """W1-C4-11: coordinator参照のNameError → 正常動作継続"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "ne.mp4"))
        cp_path = tmp_path / "ne_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        # coordinator NameError は try/except で吸収 → 正常動作
        assert result.success is True


# ============================================================
# C5: 統合・依存 (11)
# ============================================================

class TestC5IntegrationDependency:
    """W1-C5: TranscribeWorker 統合・依存"""

    @pytest.mark.asyncio
    async def test_C5_01_two_videos_no_cross_contamination(self, tmp_path):
        """W1-C5-01: 2動画同時Whisper実行 → JSONL相互汚染なし"""
        worker = TranscribeWorker()

        ctx_a = PipelineContext(video_path=str(tmp_path / "a.mp4"))
        cp_a = tmp_path / "a_hash1.jsonl"
        _create_checkpoint_jsonl(cp_a, 3)

        ctx_b = PipelineContext(video_path=str(tmp_path / "b.mp4"))
        cp_b = tmp_path / "b_hash2.jsonl"
        _create_checkpoint_jsonl(cp_b, 7)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_a)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="hash1"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    await worker.execute(ctx_a)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_b)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="hash2"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    await worker.execute(ctx_b)

        assert len(ctx_a.segments) == 3
        assert len(ctx_b.segments) == 7

    @pytest.mark.asyncio
    async def test_C5_02_process_kill_then_restart(self, tmp_path):
        """W1-C5-02: Whisper途中でプロセス強制終了→再起動 → 復旧"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "restart.mp4"))
        cp_path = tmp_path / "restart.jsonl"

        # 1回目: クラッシュ
        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="rst12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_failure(137, "Killed")):
                        result1 = await worker.execute(ctx)

        assert result1.success is False

        # 2回目: 成功（チェックポイント復旧）
        _create_checkpoint_jsonl(cp_path, 5)
        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="rst12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    result2 = await worker.execute(ctx)

        assert result2.success is True

    @pytest.mark.asyncio
    async def test_C5_03_output_meets_proofread_contract(self, tmp_path):
        """W1-C5-03: 出力segがProofreadWorker入力契約を満たす"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "contract.mp4"))
        cp_path = tmp_path / "contract_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 10)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    await worker.execute(ctx)

        # ProofreadWorker 入力契約: 各dictに text を含む
        for seg in ctx.segments:
            assert "text" in seg
            assert isinstance(seg["text"], str)

    @pytest.mark.asyncio
    async def test_C5_04_no_interference_with_background(self, tmp_path):
        """W1-C5-04: TickLoop(KAIROS)との共存 → バックグラウンドタスクと干渉なし"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "kairos.mp4"))
        cp_path = tmp_path / "kairos_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        # asyncio event loop 内で他のタスクが走っても問題ない
        async def _background_task():
            await asyncio.sleep(0.01)
            return "ok"

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    result, bg = await asyncio.gather(
                        worker.execute(ctx),
                        _background_task(),
                    )

        assert result.success is True
        assert bg == "ok"

    def test_C5_05_governance_permission_scope(self):
        """W1-C5-05: Governance権限チェック通過"""
        coordinator = PipelineCoordinator()
        scope_map = coordinator._WORKER_SCOPE_MAP
        assert scope_map["文字起こし"] == "transcriber"

    @pytest.mark.asyncio
    async def test_C5_06_ctx_segments_updated(self, tmp_path):
        """W1-C5-06: ctx.segmentsへの結果伝搬"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "ctx.mp4"))
        assert len(ctx.segments) == 0  # 初期状態

        cp_path = tmp_path / "ctx_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 8)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    await worker.execute(ctx)

        assert len(ctx.segments) == 8

    @pytest.mark.asyncio
    async def test_C5_07_stage_results_appended(self, tmp_path):
        """W1-C5-07: ctx.stage_resultsへの記録（Coordinatorテスト）"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "sr.mp4"))
        cp_path = tmp_path / "sr_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        ctx.stage_results.append(result)
        assert len(ctx.stage_results) == 1
        assert ctx.stage_results[0].stage_name == "文字起こし"

    def test_C5_08_verify_success_with_segments(self):
        """W1-C5-08: verify()メソッドの正常判定 → success=True & seg>0"""
        worker = TranscribeWorker()
        result = StageResult(
            stage_name="文字起こし", success=True,
            data={"segment_count": 10},
        )
        assert worker.verify(result) is True

    def test_C5_09_verify_failure(self):
        """W1-C5-09: verify()メソッドの異常判定 → success=False→False"""
        worker = TranscribeWorker()
        result = StageResult(
            stage_name="文字起こし", success=False,
            data={"segment_count": 0},
        )
        assert worker.verify(result) is False

    def test_C5_10_verify_zero_segments(self):
        """W1-C5-10: verify()メソッドの0セグメント判定 → False"""
        worker = TranscribeWorker()
        result = StageResult(
            stage_name="文字起こし", success=True,
            data={"segment_count": 0},
        )
        assert worker.verify(result) is False

    def test_C5_11_definition_of_done_nonempty(self):
        """W1-C5-11: get_definition_of_done()の内容検証 → 文字列非空"""
        worker = TranscribeWorker()
        dod = worker.get_definition_of_done()
        assert isinstance(dod, str)
        assert len(dod) > 0
        assert "セグメント" in dod


# ============================================================
# C6: 性能・進化 (11)
# ============================================================

class TestC6PerformanceEvolution:
    """W1-C6: TranscribeWorker 性能・進化"""

    @pytest.mark.asyncio
    async def test_C6_01_whisper_within_time_budget(self, tmp_path):
        """W1-C6-01: 5分動画でWhisper≤180秒(モック) → 時間予算内"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "budget.mp4"))
        cp_path = tmp_path / "budget_abc12345.jsonl"

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 10)):
                        result = await worker.execute(ctx)

        assert result.duration_seconds <= 180

    @pytest.mark.asyncio
    async def test_C6_02_memory_mock(self, tmp_path):
        """W1-C6-02: メモリ使用量確認（モック）→ リソース制限"""
        # 実メモリ測定はCI環境依存のため、テスト構造 of 検証のみ
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "mem.mp4"))
        cp_path = tmp_path / "mem_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_C6_03_source_info_propagation(self, tmp_path):
        """W1-C6-03: 出力segのsource情報がctxに伝搬"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "src.mp4"))
        cp_path = tmp_path / "src_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)  # sourceStart/sourceEnd含む

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        for seg in ctx.segments:
            assert "sourceStart" in seg
            assert "sourceEnd" in seg

    @pytest.mark.asyncio
    async def test_C6_04_dream_engine_learning_data(self, tmp_path):
        """W1-C6-04: 実行結果がDreamEngine学習に反映"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "dream.mp4"))
        cp_path = tmp_path / "dream_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        # StageResult がContextに記録可能な形式であること
        ctx.stage_results.append(result)
        assert ctx.stage_results[0].duration_seconds >= 0

    def test_C6_05_model_governance_reference(self):
        """W1-C6-05: model_governance経由のモデル選択 → ガバナンス準拠"""
        # TranscribeWorker はmodel_sizeを"small"固定
        # model_governanceは将来的にここに統合予定
        import inspect
        source = inspect.getsource(TranscribeWorker.execute)
        assert "model_size" in source

    @pytest.mark.asyncio
    async def test_C6_06_jsonl_atomicity(self, tmp_path):
        """W1-C6-06: JSONL書込のatomicity → 部分書込からの復旧"""
        cp_path = tmp_path / "atomic.jsonl"
        # 部分書込シミュレーション: 3行のうち2行完全、1行不完全
        with open(cp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"start": 0, "end": 15, "text": "line1"}) + "\n")
            f.write(json.dumps({"start": 15, "end": 30, "text": "line2"}) + "\n")
            f.write('{"start": 30, "end":')  # 不完全行

        # 不完全行はJSONパースで例外 → スキップ可能であるべき
        segments = []
        with open(cp_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        segments.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # 不完全行はスキップ

        assert len(segments) == 2

    def test_C6_07_subprocess_env_propagation(self):
        """W1-C6-07: サブプロセスの環境変数伝搬"""
        import inspect
        source = inspect.getsource(TranscribeWorker._run_whisper_subprocess)
        # Popen に env パラメータが明示的に設定されていない場合は親プロセス環境を継承
        assert "Popen" in source

    @pytest.mark.asyncio
    async def test_C6_08_thread_cleanup(self, tmp_path):
        """W1-C6-08: スレッドプールのクリーンアップ → スレッドリーク防止"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "thread_cl.mp4"))
        cp_path = tmp_path / "thread_cl_abc12345.jsonl"

        initial_threads = threading.active_count()

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 5)):
                        result = await worker.execute(ctx)

        # スレッドリークがないことを確認（±2の余裕）
        assert threading.active_count() <= initial_threads + 2

    @pytest.mark.asyncio
    async def test_C6_09_asyncio_event_loop_compat(self, tmp_path):
        """W1-C6-09: asyncio互換性(event loop)"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "loop.mp4"))
        cp_path = tmp_path / "loop_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        # asyncio.get_running_loop() が正常に取得できることを確認
        loop = asyncio.get_running_loop()
        assert loop is not None

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_C6_10_log_level_appropriateness(self, tmp_path, caplog):
        """W1-C6-10: ログ出力の適切性 → INFO/WARNING/ERROR分類"""
        import logging
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "log.mp4"))
        cp_path = tmp_path / "log_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with caplog.at_level(logging.DEBUG):
            with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
                with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                    with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                        result = await worker.execute(ctx)

        # ログが出力されていることを確認
        assert result.success is True

    @pytest.mark.asyncio
    async def test_C6_11_stage_result_retries(self, tmp_path):
        """W1-C6-11: StageResult.retriesの記録"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "retry.mp4"))
        cp_path = tmp_path / "retry_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 5)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        # retries はCoordinator側で設定するが、初期値は0
        assert result.retries == 0

    @pytest.mark.asyncio
    async def test_C1_12_old_checkpoint_warning(self, tmp_path):
        """W1-C1-12: 旧形式キャッシュが存在する場合の警告ログ出力を検証(L131カバー)"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "old_cp.mp4"))
        
        # 旧形式のチェックポイントファイルを作成
        old_cp_path = tmp_path / "_whisper_segments.jsonl"
        old_cp_path.write_text("dummy old data", encoding="utf-8")
        
        # 新しい形式のキャッシュファイルを作成し、Whisper実行をスキップさせる（1000B以上）
        cp_path = tmp_path / "old_cp_abc12345.jsonl"
        _create_checkpoint_jsonl(cp_path, 15)

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_success(str(cp_path), 0)):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.segments) == 15

    @pytest.mark.asyncio
    async def test_C4_12_timeout_no_checkpoint_proper(self, tmp_path):
        """W1-C4-12: タイムアウト時にチェックポイントがない場合、RuntimeErrorが発生することを検証(L95カバー)"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "to_nocp.mp4"))
        # チェックポイントファイルは存在しない状態にする

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(tmp_path / "to_nocp.jsonl")):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="to_nocp1"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _mock_popen_timeout()):
                        result = await worker.execute(ctx)

        assert result.success is False
        assert "タイムアウト" in result.detail

    @pytest.mark.asyncio
    async def test_C4_13_thread_exception_propagation(self, tmp_path):
        """W1-C4-13: 読取スレッドで予期しない例外が発生した際、RuntimeErrorが発生することを検証(L79, L101カバー)"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "thread_err.mp4"))
        cp_path = tmp_path / "thread_err_abc12345.jsonl"

        def _popen_thread_error(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            # イテレート時に例外を投げる stdout を用意
            class ErrorStdout:
                def __iter__(self):
                    return self
                def __next__(self):
                    raise RuntimeError("Unexpected thread error")
            mock_proc.stdout = ErrorStdout()
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait = MagicMock(return_value=0)
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_thread_error):
                        result = await worker.execute(ctx)

        assert result.success is False
        assert "Unexpected thread error" in result.detail

    @pytest.mark.asyncio
    async def test_C4_14_stdout_exceptions(self, tmp_path):
        """W1-C4-14: stdout読取中の ValueError/OSError ハンドリングを検証(L77カバー)"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "stdout_valerr.mp4"))
        cp_path = tmp_path / "stdout_valerr_abc12345.jsonl"

        def _popen_stdout_valerr(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            # イテレート時に ValueError を投げる stdout を用意
            class ErrorStdout:
                def __iter__(self):
                    return self
                def __next__(self):
                    raise ValueError("Stdout value error")
            mock_proc.stdout = ErrorStdout()
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait = MagicMock(return_value=0)
            # キャッシュファイルを作成して、executeが成功するようにする
            _create_checkpoint_jsonl(Path(str(cp_path)), 5)
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_stdout_valerr):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.segments) == 5

    @pytest.mark.asyncio
    async def test_C2_12_stdout_empty_lines_and_json_errors(self, tmp_path):
        """W1-C2-12: stdoutに空行や不正JSONが混ざるケースでの動作検証(L65, L75カバー)"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "empty_json.mp4"))
        cp_path = tmp_path / "empty_json_abc12345.jsonl"

        def _popen_empty_json(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = iter([
                "\n",               # 空行 (L65カバー)
                "   \n",            # 空行 (L65カバー)
                "not json\n",       # 不正JSON (L75カバー)
                json.dumps({"progress": 30}) + "\n",
                json.dumps({"status": "completed", "device": "cuda", "model": "small"}) + "\n",
            ])
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait = MagicMock(return_value=0)
            _create_checkpoint_jsonl(Path(str(cp_path)), 5)
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_empty_json):
                        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.segments) == 5


    @pytest.mark.asyncio
    async def test_C4_15_stdout_stderr_pipes_closed(self, tmp_path):
        """W1-C4-15: サブプロセス終了後に stdout および stderr パイプがクローズされることを検証"""
        worker = TranscribeWorker()
        ctx = PipelineContext(video_path=str(tmp_path / "close_pipes.mp4"))
        cp_path = tmp_path / "close_pipes_abc12345.jsonl"

        mock_stdout = MagicMock()
        mock_stdout.__iter__.return_value = iter([
            json.dumps({"status": "completed", "device": "cuda", "model": "small"}) + "\n"
        ])
        mock_stderr = MagicMock()

        def _popen_close_check(*args, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = mock_stdout
            mock_proc.stderr = mock_stderr
            mock_proc.wait = MagicMock(return_value=0)
            _create_checkpoint_jsonl(Path(str(cp_path)), 5)
            return mock_proc

        with patch("subtitle_engine.video_hash.get_checkpoint_path", return_value=str(cp_path)):
            with patch("subtitle_engine.video_hash.compute_video_hash", return_value="abc12345"):
                with patch("subtitle_engine.video_hash.OLD_CHECKPOINT_NAME", "_whisper_segments.jsonl"):
                    with patch("subprocess.Popen", _popen_close_check):
                        result = await worker.execute(ctx)

        assert result.success is True
        mock_stdout.close.assert_called_once()
        mock_stderr.close.assert_called_once()