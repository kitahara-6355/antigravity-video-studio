"""
Sprint 4.6.3 B分類最小構成カバレッジ改善テスト

対象モジュール:
- cache_manager.py (CM-01~CM-10)
- subtitle_engine/whisper_subprocess.py (WH-01~WH-12)
- design_system/design_token_manager.py (DT-01~DT-12)
"""
import sys
import os
import json
import time
import queue
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime

import pytest

# backend をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))


# ===================================================================
# CM-01~CM-10: cache_manager.py
# ===================================================================
class TestCacheManager:
    """cache_manager.py カバレッジ改善 (L57-59, L68-70, L79-80, L89-92, L96-100, L121-145)"""

    def _make_cache(self, max_size=10, default_ttl=300):
        from cache_manager import MemoryCache
        return MemoryCache(max_size=max_size, default_ttl=default_ttl)

    # CM-01: TTL超過エントリ → None + misses+1
    def test_cache_get_expired_entry(self):
        cache = self._make_cache(default_ttl=1)
        cache.set("key1", "value1")
        # TTL超過をシミュレート
        hashed = cache._make_key("key1")
        cache._cache[hashed].created_at = time.time() - 100
        result = cache.get("key1")
        assert result is None
        assert cache._stats["misses"] >= 1

    # CM-02: max_size到達 + 期限切れあり → 期限切れ削除
    def test_cache_set_evict_expired(self):
        cache = self._make_cache(max_size=2, default_ttl=300)
        cache.set("a", 1)
        cache.set("b", 2)
        # "a" を期限切れにする
        ha = cache._make_key("a")
        cache._cache[ha].created_at = time.time() - 1000
        cache._cache[ha].ttl = 1
        # max_size到達状態で新規set → 期限切れ "a" が削除される
        cache.set("c", 3)
        assert cache.get("a") is None
        assert cache.get("c") == 3

    # CM-03: max_size到達 + 全有効 → 最小hits削除
    def test_cache_set_evict_lru(self):
        cache = self._make_cache(max_size=2, default_ttl=300)
        cache.set("x", 10)
        cache.set("y", 20)
        # "y" にヒットを加えて "x" をLRU対象に
        cache.get("y")
        # max_size到達 + 全有効 → _evict_lru呼出
        cache.set("z", 30)
        # "x" (hits=0) が削除され、"y" と "z" が残る
        assert cache.get("x") is None
        assert cache.get("z") == 30

    # CM-04: 存在するキー削除 → True
    def test_cache_delete_existing(self):
        cache = self._make_cache()
        cache.set("del_key", "val")
        result = cache.delete("del_key")
        assert result is True
        assert cache.get("del_key") is None

    # CM-05: 存在しないキー → False
    def test_cache_delete_nonexistent(self):
        cache = self._make_cache()
        result = cache.delete("no_such_key")
        assert result is False

    # CM-06: _evict_expired → 削除件数返却
    def test_cache_evict_expired_count(self):
        cache = self._make_cache(max_size=10, default_ttl=1)
        cache.set("e1", 1)
        cache.set("e2", 2)
        cache.set("e3", 3)
        # 全エントリを期限切れにする
        for entry in cache._cache.values():
            entry.created_at = time.time() - 100
        count = cache._evict_expired()
        assert count == 3
        assert len(cache._cache) == 0

    # CM-07: 空キャッシュ → 何もしない
    def test_cache_evict_lru_empty(self):
        cache = self._make_cache()
        # 空キャッシュで _evict_lru を呼んでもエラーにならない
        cache._evict_lru()
        assert len(cache._cache) == 0

    # CM-08: hits/misses/size/hit_rate 計算
    def test_cache_stats(self):
        cache = self._make_cache()
        cache.set("s1", "v1")
        cache.get("s1")  # hit
        cache.get("s1")  # hit
        cache.get("missing")  # miss
        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["hit_rate"] == round(2 / 3, 3)

    # CM-09: 2回目呼出 → キャッシュヒット
    def test_cached_decorator_hit(self):
        from cache_manager import MemoryCache, cached
        test_cache = MemoryCache(max_size=10, default_ttl=300)
        call_count = 0

        @cached(cache=test_cache)
        def expensive_fn(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        r1 = expensive_fn(5)
        r2 = expensive_fn(5)
        assert r1 == 10
        assert r2 == 10
        assert call_count == 1  # 2回目はキャッシュヒット

    # CM-10: 初回呼出 → ミス + 結果保存
    def test_cached_decorator_miss(self):
        from cache_manager import MemoryCache, cached
        test_cache = MemoryCache(max_size=10, default_ttl=300)

        @cached(cache=test_cache)
        def compute(a, b):
            return a + b

        result = compute(3, 4)
        assert result == 7
        assert test_cache._stats["misses"] == 1
        # 保存されていることを確認 (2回目呼出でヒット)
        result2 = compute(3, 4)
        assert result2 == 7
        assert test_cache._stats["hits"] == 1


# ===================================================================
# WH-01~WH-12: subtitle_engine/whisper_subprocess.py
# ===================================================================
class TestWhisperSubprocess:
    """whisper_subprocess.py カバレッジ改善 (ヘルパー関数 + main)"""

    # WH-01: WAV存在+新しい → 再利用
    def test_extract_audio_reuse_existing(self, tmp_path):
        from subtitle_engine.whisper_subprocess import extract_audio_wav
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake_video")
        # videoのmtimeを古くする
        old_time = time.time() - 100
        os.utime(str(video), (old_time, old_time))
        wav = tmp_path / "_whisper_audio.wav"
        wav.write_bytes(b"fake_wav")
        # WAVが新しい → 再利用パス
        result = extract_audio_wav(str(video), str(tmp_path))
        assert result == str(wav)

    # WH-02: subprocess正常 → wav_path返却
    def test_extract_audio_success(self, tmp_path):
        from subtitle_engine.whisper_subprocess import extract_audio_wav
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake_video")
        mock_result = MagicMock(returncode=0, stderr="")
        wav_path = tmp_path / "_whisper_audio.wav"

        def _create_wav(*args, **kwargs):
            wav_path.write_bytes(b"x" * 2048)
            return mock_result

        with patch("subprocess.run", side_effect=_create_wav):
            result = extract_audio_wav(str(video), str(tmp_path))
        assert result == str(wav_path)

    # WH-03: returncode!=0 → RuntimeError
    def test_extract_audio_failure(self, tmp_path):
        from subtitle_engine.whisper_subprocess import extract_audio_wav
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake_video")
        mock_result = MagicMock(returncode=1, stderr="ffmpeg error")
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="FFmpeg failed"):
                extract_audio_wav(str(video), str(tmp_path))

    # WH-04: 総長 < chunk_sec → チャンク分割なし
    def test_split_wav_short_audio(self, tmp_path):
        from subtitle_engine.whisper_subprocess import split_wav_chunks
        wav = tmp_path / "short.wav"
        wav.write_bytes(b"x" * 2000)
        mock_probe = MagicMock(stdout="120.0\n")
        with patch("subprocess.run", return_value=mock_probe):
            chunks = split_wav_chunks(str(wav), str(tmp_path), chunk_sec=300)
        assert len(chunks) == 1
        assert chunks[0][0] == str(wav)
        assert chunks[0][1] == 0.0

    # WH-05: 総長 > chunk_sec → 複数チャンク
    def test_split_wav_multiple_chunks(self, tmp_path):
        from subtitle_engine.whisper_subprocess import split_wav_chunks
        wav = tmp_path / "long.wav"
        wav.write_bytes(b"x" * 2000)

        call_count = [0]

        def mock_run(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # ffprobe duration
                return MagicMock(stdout="600.0\n")
            else:
                # ffmpeg split - create chunk files
                cmd_args = args[0]
                for i, arg in enumerate(cmd_args):
                    if str(arg).endswith(".wav") and "_chunk_" in str(arg):
                        Path(arg).write_bytes(b"x" * 2000)
                        break
                return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            chunks = split_wav_chunks(str(wav), str(tmp_path), chunk_sec=300)
        assert len(chunks) == 2

    # WH-06: チャンクファイル < 1000バイト → スキップ
    def test_split_wav_skip_small_chunk(self, tmp_path):
        from subtitle_engine.whisper_subprocess import split_wav_chunks
        wav = tmp_path / "test.wav"
        wav.write_bytes(b"x" * 2000)

        call_count = [0]

        def mock_run(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(stdout="600.0\n")
            else:
                cmd_args = args[0]
                for i, arg in enumerate(cmd_args):
                    if str(arg).endswith(".wav") and "_chunk_" in str(arg):
                        # 小さいファイル (<1000 bytes)
                        Path(arg).write_bytes(b"x" * 500)
                        break
                return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            chunks = split_wav_chunks(str(wav), str(tmp_path), chunk_sec=300)
        assert len(chunks) == 0  # 全チャンクが小さすぎてスキップ

    # WH-07: model.transcribe正常 → セグメント返却
    def test_transcribe_chunk_success(self, tmp_path):
        from subtitle_engine.whisper_subprocess import transcribe_chunk
        mock_seg = MagicMock(start=0.0, end=2.5, text=" テスト ")
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_seg]), None)
        chunk = tmp_path / "chunk.wav"
        chunk.write_bytes(b"x" * 2000)
        result = transcribe_chunk(mock_model, str(chunk), 10.0, "ja", 0, 1)
        assert len(result) == 1
        assert result[0]["start"] == 10.0
        assert result[0]["end"] == 12.5
        assert result[0]["text"] == "テスト"

    # WH-08: _run例外 → 空リスト
    def test_transcribe_chunk_error(self, tmp_path):
        from subtitle_engine.whisper_subprocess import transcribe_chunk
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("GPU error")
        chunk = tmp_path / "chunk.wav"
        chunk.write_bytes(b"x" * 2000)
        result = transcribe_chunk(mock_model, str(chunk), 0.0, "ja", 0, 1)
        assert result == []

    # WH-09: CHUNK_TIMEOUT超過 → 空リスト
    def test_transcribe_chunk_timeout(self, tmp_path):
        from subtitle_engine.whisper_subprocess import transcribe_chunk
        mock_model = MagicMock()

        def _hang(*args, **kwargs):
            import time as t
            t.sleep(10)
            return (iter([]), None)

        mock_model.transcribe.side_effect = _hang
        chunk = tmp_path / "chunk.wav"
        chunk.write_bytes(b"x" * 2000)
        with patch("subtitle_engine.whisper_subprocess.CHUNK_TIMEOUT", 0.1):
            result = transcribe_chunk(mock_model, str(chunk), 0.0, "ja", 0, 1)
        assert result == []

    # WH-10: 引数不足 → JSON error + sys.exit(1)
    def test_main_usage_error(self):
        from subtitle_engine.whisper_subprocess import main
        with patch("sys.argv", ["whisper_subprocess.py"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1

    # WH-11: 正常フロー → JSON status=completed
    def test_main_success_flow(self, tmp_path, capsys):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "output.jsonl"

        mock_seg = MagicMock(start=0.0, end=2.0, text=" hello ")
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_seg]), None)

        mock_whisper_cls = MagicMock(return_value=mock_model)
        mock_probe = MagicMock(stdout="30.0\n", returncode=0)
        mock_extract = MagicMock(returncode=0)

        # WAV/chunkファイル作成用
        wav_path = tmp_path / "_whisper_audio.wav"

        def mock_run_fn(cmd, *args, **kwargs):
            if "ffprobe" in str(cmd[0]):
                return mock_probe
            if "ffmpeg" in str(cmd[0]):
                wav_path.write_bytes(b"x" * 2000)
                return mock_extract
            return MagicMock(returncode=0)

        mock_exit = MagicMock()

        with patch("sys.argv", ["whisper_subprocess.py", str(video), str(output), "small", "ja"]):
            with patch.dict("sys.modules", {"ctranslate2": MagicMock(get_supported_compute_types=MagicMock(side_effect=Exception("no CUDA")))}):
                with patch("subprocess.run", side_effect=mock_run_fn):
                    with patch("subtitle_engine.whisper_subprocess.extract_audio_wav", return_value=str(wav_path)):
                        with patch("subtitle_engine.whisper_subprocess.split_wav_chunks", return_value=[(str(wav_path), 0.0, 30.0)]):
                            with patch("subtitle_engine.whisper_subprocess.transcribe_chunk", return_value=[{"start": 0.0, "end": 2.0, "text": "hello", "sourceStart": 0.0, "sourceEnd": 2.0}]):
                                with patch("os._exit", mock_exit):
                                    # faster_whisper をモック注入
                                    import subtitle_engine.whisper_subprocess as ws_mod
                                    with patch.object(ws_mod, "__name__", ws_mod.__name__):
                                        with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=mock_whisper_cls)}):
                                            main_mod = ws_mod.main
                                            main_mod()

        mock_exit.assert_called_with(0)

    # WH-12: 全体例外 → JSON status=error
    def test_main_exception(self, tmp_path):
        from subtitle_engine.whisper_subprocess import main
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "output.jsonl"
        mock_exit = MagicMock()
        with patch("sys.argv", ["whisper_subprocess.py", str(video), str(output)]):
            with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=MagicMock(side_effect=Exception("fatal")))}):
                with patch("os._exit", mock_exit):
                    main()
        mock_exit.assert_called_with(1)


# ===================================================================
# DT-01~DT-12: design_system/design_token_manager.py
# ===================================================================
class TestDesignTokenManager:
    """design_token_manager.py カバレッジ改善 (mood fallback, update_tokens, cache, evolution_log, frontend tokens)"""

    @pytest.fixture
    def dtm_env(self, tmp_path):
        """tmp_pathベースのDesignTokenManagerを構築"""
        from design_system.design_token_manager import DesignTokenManager
        mgr = DesignTokenManager()
        # パスをtmp_pathにリダイレクト
        mgr._branding_dir = tmp_path
        mgr._constitution_path = tmp_path / "constitution.json"
        mgr._history_path = tmp_path / "design_tokens_history.json"
        mgr._evolution_log_path = tmp_path / "evolution_log.json"
        mgr._design_tokens_path = tmp_path / "design_tokens.json"
        mgr._cache = None
        mgr._cache_mtime = 0
        # 初期constitution.json作成
        constitution = {
            "design_tokens": {
                "elegant": {
                    "color_palette": {"primary": "#1A1A2E", "accent": "#E94560"},
                    "typography": {"font_family": "Noto Sans JP"},
                    "motion": {"transition": "0.3s ease"},
                    "imagen_prompt_suffix": "elegant cinematic",
                    "veo_prompt_suffix": "smooth elegant motion"
                },
                "dynamic": {
                    "color_palette": {"primary": "#FF6B00"},
                    "imagen_prompt_suffix": "dynamic energetic",
                    "veo_prompt_suffix": "fast dynamic motion"
                }
            }
        }
        mgr._constitution_path.write_text(json.dumps(constitution), encoding="utf-8")
        return mgr

    # DT-01: 未知mood → elegant fallback + warning
    def test_get_tokens_mood_fallback(self, dtm_env):
        tokens = dtm_env.get_tokens(mood="unknown_mood")
        assert "color_palette" in tokens
        assert tokens["color_palette"]["primary"] == "#1A1A2E"

    # DT-02: 全ムード辞書返却
    def test_get_all_tokens(self, dtm_env):
        all_tokens = dtm_env.get_all_tokens()
        assert "elegant" in all_tokens
        assert "dynamic" in all_tokens

    # DT-03: mood指定 → color_palette辞書
    def test_get_color_palette(self, dtm_env):
        palette = dtm_env.get_color_palette(mood="elegant")
        assert palette["primary"] == "#1A1A2E"
        assert palette["accent"] == "#E94560"

    # DT-03-2: typography取得
    def test_get_typography(self, dtm_env):
        typography = dtm_env.get_typography(mood="elegant")
        assert typography["font_family"] == "Noto Sans JP"

    # DT-03-3: motion取得
    def test_get_motion(self, dtm_env):
        motion = dtm_env.get_motion(mood="elegant")
        assert motion["transition"] == "0.3s ease"

    # DT-04: api_type=imagen → imagen_prompt_suffix
    def test_get_prompt_suffix_imagen(self, dtm_env):
        suffix = dtm_env.get_prompt_suffix(mood="elegant", api_type="imagen")
        assert suffix == "elegant cinematic"

    # DT-05: api_type=veo → veo_prompt_suffix
    def test_get_prompt_suffix_veo(self, dtm_env):
        suffix = dtm_env.get_prompt_suffix(mood="elegant", api_type="veo")
        assert suffix == "smooth elegant motion"

    # DT-05-2: api_type=unknown → ""
    def test_get_prompt_suffix_unknown(self, dtm_env):
        suffix = dtm_env.get_prompt_suffix(mood="elegant", api_type="unknown")
        assert suffix == ""

    # DT-06: dict更新 → deep merge + 履歴記録
    def test_update_tokens_deep_merge(self, dtm_env):
        result = dtm_env.update_tokens(
            mood="elegant",
            updates={"color_palette": {"accent": "#FF0000"}},
            source="test",
            reason="テスト更新"
        )
        assert result["status"] == "updated"
        # deep merge: primaryは残り、accentだけ変更
        tokens = dtm_env.get_tokens("elegant")
        assert tokens["color_palette"]["primary"] == "#1A1A2E"
        assert tokens["color_palette"]["accent"] == "#FF0000"

    # DT-07: update後 → _cache=None
    def test_update_tokens_cache_invalidation(self, dtm_env):
        # キャッシュを作成
        dtm_env.get_tokens("elegant")
        assert dtm_env._cache is not None
        # update_tokens後にキャッシュが無効化される
        dtm_env.update_tokens(mood="elegant", updates={"new_key": "val"})
        assert dtm_env._cache is None

    # DT-08: 2回目ロード → キャッシュヒット
    def test_load_constitution_cache_hit(self, dtm_env):
        # 1回目: ファイルから読込
        data1 = dtm_env._load_constitution()
        assert dtm_env._cache is not None
        # 2回目: キャッシュから
        data2 = dtm_env._load_constitution()
        assert data1 == data2

    # DT-09: constitutionファイル破損 → 空dict + error log
    def test_load_constitution_exception(self, dtm_env):
        dtm_env._cache = None
        dtm_env._constitution_path.write_text("invalid json{{{", encoding="utf-8")
        result = dtm_env._load_constitution()
        assert result == {}

    # DT-09-2: load_historyでの例外処理
    def test_load_history_exception(self, dtm_env):
        # 履歴ファイルが存在するが無効なJSONの場合
        dtm_env._history_path.write_text("invalid json{{{", encoding="utf-8")
        result = dtm_env._load_history()
        assert result == {"changes": []}

    # DT-09-3: 履歴取得のlimit制御
    def test_get_change_history_limit(self, dtm_env):
        # 複数回更新を行う
        dtm_env.update_tokens(mood="elegant", updates={"key1": "val1"}, source="t1")
        dtm_env.update_tokens(mood="elegant", updates={"key2": "val2"}, source="t2")
        
        # limitあり
        history_limit_1 = dtm_env.get_change_history(limit=1)
        assert len(history_limit_1) == 1
        assert history_limit_1[0]["source"] == "t2"
        
        # limit=0 (全件)
        history_all = dtm_env.get_change_history(limit=0)
        assert len(history_all) >= 2

    # DT-10: 変更 → evolution_log.jsonにエントリ追加
    def test_record_to_evolution_log(self, dtm_env):
        dtm_env.update_tokens(
            mood="elegant",
            updates={"motion": {"transition": "0.5s ease-in"}},
            source="chat",
            reason="モーション調整"
        )
        evo_log = json.loads(dtm_env._evolution_log_path.read_text(encoding="utf-8"))
        assert len(evo_log["entries"]) >= 1
        entry = evo_log["entries"][-1]
        assert entry["type"] == "design_token_change"
        assert "elegant" in entry["summary"]

    # DT-10-2: 進化ログが既に存在する場合の読み込みパス
    def test_record_to_evolution_log_existing(self, dtm_env):
        # 既存の進化ログを作成
        existing_log = {"entries": [{"type": "initial"}]}
        dtm_env._evolution_log_path.write_text(json.dumps(existing_log), encoding="utf-8")
        
        dtm_env.update_tokens(
            mood="elegant",
            updates={"motion": {"transition": "0.5s ease-in"}},
            source="chat"
        )
        evo_log = json.loads(dtm_env._evolution_log_path.read_text(encoding="utf-8"))
        assert len(evo_log["entries"]) == 2
        assert evo_log["entries"][0]["type"] == "initial"
        assert evo_log["entries"][1]["type"] == "design_token_change"

    # DT-11: 記録例外 → warning + 処理続行
    def test_record_to_evolution_log_exception(self, dtm_env):
        # evolution_log_pathをディレクトリにして書込み不可にする
        dtm_env._evolution_log_path.mkdir(exist_ok=True)
        # 例外が発生しても_record_to_evolution_logはwarningで処理続行
        dtm_env._record_to_evolution_log(
            "elegant", {"key": "val"}, {}, "test", "reason"
        )
        # 例外でクラッシュしないことを確認

    # DT-11-2: get_frontend_tokens での例外
    def test_get_frontend_tokens_exception(self, dtm_env):
        # 壊れたJSONを書き込んで例外を発生させる
        dtm_env._design_tokens_path.write_text("invalid json{{{", encoding="utf-8")
        result = dtm_env.get_frontend_tokens()
        assert result is None

    # DT-12: theme/category更新 → evo_log記録
    def test_update_frontend_tokens_success(self, dtm_env):
        # frontend design_tokens.json を作成
        frontend_tokens = {
            "themes": {
                "dark": {
                    "color": {"bg": "#000", "text": "#fff"},
                    "typography": {"size": "16px"}
                }
            }
        }
        dtm_env._design_tokens_path.write_text(
            json.dumps(frontend_tokens), encoding="utf-8"
        )
        result = dtm_env.update_frontend_tokens(
            theme="dark",
            category="color",
            updates={"bg": "#111"},
            source="manual",
            reason="背景色調整"
        )
        assert result["status"] == "updated"
        assert result["theme"] == "dark"
        # ファイルが更新されている
        updated = json.loads(dtm_env._design_tokens_path.read_text(encoding="utf-8"))
        assert updated["themes"]["dark"]["color"]["bg"] == "#111"
        assert updated["themes"]["dark"]["color"]["text"] == "#fff"

    # DT-12-2: update_frontend_tokens で json ファイルが存在しない
    def test_update_frontend_tokens_not_found(self, dtm_env):
        # ファイルがない
        if dtm_env._design_tokens_path.exists():
            dtm_env._design_tokens_path.unlink()
        result = dtm_env.update_frontend_tokens(
            theme="dark",
            category="color",
            updates={"bg": "#111"}
        )
        assert result["status"] == "error"
        assert "not found" in result["message"]

    # DT-12-3: update_frontend_tokens で theme が見つからない
    def test_update_frontend_tokens_theme_not_found(self, dtm_env):
        frontend_tokens = {"themes": {"dark": {"color": {}}}}
        dtm_env._design_tokens_path.write_text(json.dumps(frontend_tokens), encoding="utf-8")
        result = dtm_env.update_frontend_tokens(
            theme="light",
            category="color",
            updates={"bg": "#111"}
        )
        assert result["status"] == "error"
        assert "theme 'light' not found" in result["message"]

    # DT-12-4: update_frontend_tokens で category が見つからない
    def test_update_frontend_tokens_category_not_found(self, dtm_env):
        frontend_tokens = {"themes": {"dark": {"color": {}}}}
        dtm_env._design_tokens_path.write_text(json.dumps(frontend_tokens), encoding="utf-8")
        result = dtm_env.update_frontend_tokens(
            theme="dark",
            category="typography",
            updates={"size": "14px"}
        )
        assert result["status"] == "error"
        assert "category 'typography' not found" in result["message"]

    # DT-12-5: update_frontend_tokens でネストされた辞書の deep merge
    def test_update_frontend_tokens_deep_merge(self, dtm_env):
        frontend_tokens = {
            "themes": {
                "dark": {
                    "color": {
                        "bg": {"primary": "#000", "secondary": "#222"}
                    }
                }
            }
        }
        dtm_env._design_tokens_path.write_text(json.dumps(frontend_tokens), encoding="utf-8")
        result = dtm_env.update_frontend_tokens(
            theme="dark",
            category="color",
            updates={"bg": {"primary": "#111"}},
            source="manual",
            reason="ネストされた背景色調整"
        )
        assert result["status"] == "updated"
        updated = json.loads(dtm_env._design_tokens_path.read_text(encoding="utf-8"))
        # primaryだけ更新され、secondaryは維持されていること
        assert updated["themes"]["dark"]["color"]["bg"]["primary"] == "#111"
        assert updated["themes"]["dark"]["color"]["bg"]["secondary"] == "#222"
