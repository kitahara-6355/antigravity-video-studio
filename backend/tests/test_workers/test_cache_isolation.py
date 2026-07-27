"""
M1.3 キャッシュ固有化テスト (T-027〜T-030)

T-027: SHA256先頭8文字の算出 (3テスト)
T-028: チェックポイントパスにハッシュを含める (2テスト)
T-029: 古い形式のJSONLキャッシュを無視 (2テスト)
T-030: 異なる動画でキャッシュが共有されないことを確認 (2テスト)
"""

import pytest
import json
import hashlib
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agents.pipeline_coordinator import TranscribeWorker, PipelineContext


# ============================================================
# ヘルパー: 1000バイト超のJSONLキャッシュファイルを生成
# ============================================================

def _write_cache_jsonl(path, segments, *, min_bytes=1100):
    """キャッシュファイルを書き出す。st_size > 1000 を確実に超えるようテキストを調整"""
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    # サイズが足りなければパディング行を追加
    while Path(path).stat().st_size < min_bytes:
        padding_seg = {"start": 999, "end": 999.5, "text": "パディングテキスト" * 10}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(padding_seg, ensure_ascii=False) + "\n")


def _make_mock_popen(cache_path_to_write, segments_to_write):
    """subprocess.Popen のモックファクトリ。指定パスにJSONLを書き出す"""
    def mock_popen(*args, **kwargs):
        _write_cache_jsonl(cache_path_to_write, segments_to_write)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            '{"progress": 100}\n',
            '{"status": "completed", "device": "cpu", "model": "small"}\n',
        ])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        mock_proc.kill.return_value = None
        return mock_proc
    return mock_popen


# ============================================================
# T-027: 動画ファイルのSHA256先頭8文字を算出する関数
# ============================================================

class TestT027VideoHash:
    """T-027: compute_video_hash のユニットテスト"""

    def test_hash_length_and_hex(self, tmp_path):
        """ハッシュが正確に8文字の16進数であること"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video content for hash test")

        from subtitle_engine.video_hash import compute_video_hash
        result = compute_video_hash(str(video))

        assert len(result) == 8, f"ハッシュ長が8でない: {len(result)}"
        int(result, 16)  # 16進数パース可能であること

    def test_hash_deterministic(self, tmp_path):
        """同じファイルに対して同じハッシュが返ること（決定性）"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"deterministic test content")

        from subtitle_engine.video_hash import compute_video_hash
        h1 = compute_video_hash(str(video))
        h2 = compute_video_hash(str(video))

        assert h1 == h2, f"同一ファイルで異なるハッシュ: {h1} != {h2}"

    def test_hash_matches_manual_sha256(self, tmp_path):
        """手動計算のSHA256先頭8文字と一致すること"""
        content = b"manual verification content"
        video = tmp_path / "verify.mp4"
        video.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()[:8]

        from subtitle_engine.video_hash import compute_video_hash
        assert compute_video_hash(str(video)) == expected


# ============================================================
# T-028: チェックポイントJSONLのパスにハッシュを含める
# ============================================================

class TestT028CheckpointPath:
    """T-028: ハッシュ付きチェックポイントパスの検証"""

    def test_checkpoint_path_format(self, tmp_path):
        """get_checkpoint_path が _whisper_{hash8}.jsonl 形式を返すこと"""
        video = tmp_path / "test_video.mp4"
        video.write_bytes(b"checkpoint path test content")

        from subtitle_engine.video_hash import compute_video_hash, get_checkpoint_path
        video_hash = compute_video_hash(str(video))
        cp_path = get_checkpoint_path(str(video))

        expected_name = f"_whisper_{video_hash}.jsonl"
        assert Path(cp_path).name == expected_name
        assert Path(cp_path).parent == tmp_path

    @pytest.mark.asyncio
    async def test_transcribe_worker_uses_hash_path(self, tmp_path):
        """TranscribeWorker がハッシュ付きパスでキャッシュヒットすること"""
        # 動画ファイル作成
        video = tmp_path / "cached_video.mp4"
        video.write_bytes(b"cached video content")

        # ハッシュ付きチェックポイント作成（1000バイト超を保証）
        from subtitle_engine.video_hash import compute_video_hash
        video_hash = compute_video_hash(str(video))
        cp_path = tmp_path / f"_whisper_{video_hash}.jsonl"

        segments_data = [
            {"start": i * 3.0, "end": (i + 1) * 3.0,
             "text": f"これはキャッシュテスト用のセグメント番号{i}です。十分な長さのテキストを含んでいます。"}
            for i in range(10)
        ]
        _write_cache_jsonl(cp_path, segments_data)

        # TranscribeWorker実行 — キャッシュヒットすべき
        ctx = PipelineContext(video_path=str(video))
        worker = TranscribeWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert "キャッシュ" in result.detail
        assert result.data.get("model") == "cached"
        assert len(ctx.segments) >= 10


# ============================================================
# T-029: 古い形式のJSONLキャッシュを無視するロジック
# ============================================================

class TestT029OldCacheIgnored:
    """T-029: 旧形式 _whisper_segments.jsonl を無視する検証"""

    @pytest.mark.asyncio
    async def test_old_format_cache_ignored(self, tmp_path):
        """旧形式 _whisper_segments.jsonl が存在してもキャッシュヒットしないこと"""
        video = tmp_path / "test_video.mp4"
        video.write_bytes(b"old cache test content")

        # 旧形式キャッシュを配置（1000バイト超）
        old_cache = tmp_path / "_whisper_segments.jsonl"
        old_segments = [
            {"start": i * 3.0, "end": (i + 1) * 3.0,
             "text": f"旧形式のセグメント{i}番 — このテキストは無視されるべきです。充分な長さが必要です。"}
            for i in range(10)
        ]
        _write_cache_jsonl(old_cache, old_segments)

        # 新形式キャッシュは存在しない → Whisper実行が必要
        from subtitle_engine.video_hash import compute_video_hash
        video_hash = compute_video_hash(str(video))
        new_cache_path = tmp_path / f"_whisper_{video_hash}.jsonl"

        # Whisperサブプロセスをモック: 新形式キャッシュを書き出す
        new_segments = [
            {"start": i * 2.0, "end": (i + 1) * 2.0,
             "text": f"新セグメント{i}番のテキストです。Whisperが生成した新しいデータです。"}
            for i in range(5)
        ]

        ctx = PipelineContext(video_path=str(video))
        worker = TranscribeWorker()

        with patch("subprocess.Popen",
                   side_effect=_make_mock_popen(new_cache_path, new_segments)):
            result = await worker.execute(ctx)

        assert result.success is True
        # 旧キャッシュ(10seg)ではなく新キャッシュ(5seg+パディング)から読み込まれたことを確認
        assert ctx.segments[0]["text"].startswith("新セグメント0")

    @pytest.mark.asyncio
    async def test_old_cache_warning_logged(self, tmp_path):
        """旧形式キャッシュ検出時に警告ログが出力されること"""
        video = tmp_path / "test_video.mp4"
        video.write_bytes(b"warning log test content")

        # 旧形式キャッシュを配置
        old_cache = tmp_path / "_whisper_segments.jsonl"
        old_cache.write_text('{"start":0,"end":3,"text":"old"}\n' * 50, encoding="utf-8")

        # 新形式キャッシュも配置（キャッシュヒットさせる）
        from subtitle_engine.video_hash import compute_video_hash
        video_hash = compute_video_hash(str(video))
        new_cache = tmp_path / f"_whisper_{video_hash}.jsonl"
        new_segments = [
            {"start": i * 3.0, "end": (i + 1) * 3.0,
             "text": f"新形式キャッシュのセグメント{i}です。このテキストは十分な長さを確保するために書かれています。"}
            for i in range(10)
        ]
        _write_cache_jsonl(new_cache, new_segments)

        ctx = PipelineContext(video_path=str(video))
        worker = TranscribeWorker()

        import logging
        # Sprint D: Worker分離後はロガーがWorkerモジュール側にある
        worker_logger = logging.getLogger("agents.workers.transcribe_worker")
        with patch.object(worker_logger, "info",
                         wraps=worker_logger.info) as mock_log:
            result = await worker.execute(ctx)

        assert result.success is True
        # 旧キャッシュ警告がログに出力されたことを確認
        log_messages = [str(call) for call in mock_log.call_args_list]
        assert any("旧形式" in msg for msg in log_messages), \
            f"旧形式キャッシュ警告が出力されていない: {log_messages}"


# ============================================================
# T-030: 異なる動画でキャッシュが共有されないことを確認
# ============================================================

class TestT030CacheIsolation:
    """T-030: 異なる動画のキャッシュ分離テスト"""

    def test_different_videos_different_hashes(self, tmp_path):
        """異なる動画ファイルは異なるハッシュ→異なるキャッシュパスを持つ"""
        v1 = tmp_path / "video_A.mp4"
        v2 = tmp_path / "video_B.mp4"
        v1.write_bytes(b"content of video A - unique data")
        v2.write_bytes(b"content of video B - different data")

        from subtitle_engine.video_hash import compute_video_hash, get_checkpoint_path
        h1 = compute_video_hash(str(v1))
        h2 = compute_video_hash(str(v2))

        assert h1 != h2, f"異なる動画で同一ハッシュ: {h1}"

        path1 = get_checkpoint_path(str(v1))
        path2 = get_checkpoint_path(str(v2))
        assert path1 != path2, "異なる動画で同一チェックポイントパス"

    @pytest.mark.asyncio
    async def test_cache_not_shared_between_videos(self, tmp_path):
        """動画Aのキャッシュが動画Bの実行に影響しないこと"""
        # 動画A: キャッシュあり
        video_a = tmp_path / "video_A.mp4"
        video_a.write_bytes(b"video A content for isolation test")

        from subtitle_engine.video_hash import compute_video_hash
        hash_a = compute_video_hash(str(video_a))
        cache_a = tmp_path / f"_whisper_{hash_a}.jsonl"

        a_segments = [
            {"start": i * 5.0, "end": (i + 1) * 5.0,
             "text": f"動画Aのセグメント{i}です。このテキストは十分な長さを確保するために書かれている長いテキストです。"}
            for i in range(10)
        ]
        _write_cache_jsonl(cache_a, a_segments)

        # 動画B: 同じディレクトリだがキャッシュなし
        video_b = tmp_path / "video_B.mp4"
        video_b.write_bytes(b"video B content for isolation test - different")

        hash_b = compute_video_hash(str(video_b))
        cache_b = tmp_path / f"_whisper_{hash_b}.jsonl"

        # 動画Aのキャッシュは存在するが、動画Bのキャッシュは存在しない
        assert cache_a.exists()
        assert not cache_b.exists()

        # 動画AはキャッシュヒットしてWhisperスキップ
        ctx_a = PipelineContext(video_path=str(video_a))
        worker_a = TranscribeWorker()
        result_a = await worker_a.execute(ctx_a)
        assert result_a.success is True
        assert result_a.data.get("model") == "cached"
        assert ctx_a.segments[0]["text"].startswith("動画Aのセグメント0")

        # 動画BはキャッシュヒットせずWhisper実行が必要
        b_segments = [
            {"start": 0, "end": 3, "text": "動画Bのセグメント1のテキストです。新しいWhisper実行結果。"},
            {"start": 3, "end": 6, "text": "動画Bのセグメント2のテキストです。新しいWhisper実行結果。"},
        ]

        ctx_b = PipelineContext(video_path=str(video_b))
        worker_b = TranscribeWorker()

        with patch("subprocess.Popen",
                   side_effect=_make_mock_popen(cache_b, b_segments)):
            result_b = await worker_b.execute(ctx_b)

        assert result_b.success is True
        assert result_b.data.get("model") != "cached"  # Whisper実行
        assert ctx_b.segments[0]["text"].startswith("動画Bのセグメント1")

        # 動画Aのキャッシュは変化していないこと
        with open(cache_a, "r", encoding="utf-8") as f:
            a_cached = [json.loads(line) for line in f if line.strip()]
        assert a_cached[0]["text"].startswith("動画Aのセグメント0")
