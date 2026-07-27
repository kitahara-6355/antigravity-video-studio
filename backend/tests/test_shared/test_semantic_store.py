"""
M2.5: Semantic Store テスト — ロバストネス・カオス耐性テストの追加

semantic_store.py のカオステスト・ロバストネステストを追加し、例外ハンドリングの強化とフォールバックの動作を検証します。
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


@pytest.fixture
def mock_gemini():
    """Gemini APIモック"""
    with patch("semantic_store.get_gemini_client") as mock_client, \
         patch("semantic_store.get_model", return_value="gemini-test"):
        client = MagicMock()
        mock_client.return_value = client
        yield client


@pytest.fixture
def store(mock_gemini, tmp_path):
    """テスト用SemanticSubtitleStoreV2"""
    from semantic_store import SemanticSubtitleStoreV2
    s = SemanticSubtitleStoreV2.__new__(SemanticSubtitleStoreV2)
    s.store_path = None
    s.cache_dir = tmp_path / "cache"
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    s.segments = []
    s.topics = []
    s.key_moments = []
    s.metadata = {}
    s.stats = {"api_calls": 0, "cache_hits": 0, "fallbacks": 0}
    s.client = mock_gemini
    s.model = "gemini-test"
    return s


def _make_segments(n=5):
    """テスト用セグメント生成"""
    return [
        {"id": f"seg_{i:03d}", "text": f"テスト文字列{i}", "start": i * 10.0, "end": (i + 1) * 10.0}
        for i in range(n)
    ]


# ============================================================
# SemanticSubtitleStoreV2 テスト
# ============================================================

class TestSemanticSubtitleStoreV2:
    """SemanticSubtitleStoreV2: セマンティック字幕分析"""

    def test_quick_analyze_all_basic(self, store):
        """_quick_analyze_all: 基本分析"""
        segments = _make_segments(5)
        store._quick_analyze_all(segments)
        assert len(store.segments) == 5
        assert store.segments[0].id == "seg_000"

    def test_quick_analyze_high_importance_keyword(self, store):
        """_quick_analyze_all: 重要キーワード → importance 0.8"""
        segments = [{"id": "s1", "text": "これは本質的なポイントです", "start": 0, "end": 10}]
        store._quick_analyze_all(segments)
        assert store.segments[0].importance == 0.8
        assert store.segments[0].highlight_candidate is True

    def test_quick_analyze_telop_candidate(self, store):
        """_quick_analyze_all: 重要キーワード + 短文 → テロップ候補"""
        segments = [{"id": "s1", "text": "大切なこと", "start": 0, "end": 5}]
        store._quick_analyze_all(segments)
        assert store.segments[0].telop_candidate is True

    def test_quick_analyze_mid_importance(self, store):
        """_quick_analyze_all: 中重要度キーワード"""
        segments = [{"id": "s1", "text": "なるほど、そういうことですね", "start": 0, "end": 5}]
        store._quick_analyze_all(segments)
        assert store.segments[0].importance == 0.6

    def test_quick_analyze_short_utterance(self, store):
        """_quick_analyze_all: 短い相槌 → 低重要度"""
        segments = [{"id": "s1", "text": "はい", "start": 0, "end": 1}]
        store._quick_analyze_all(segments)
        assert store.segments[0].importance == 0.3

    def test_quick_analyze_default_id(self, store):
        """_quick_analyze_all: id未指定時はデフォルト"""
        segments = [{"text": "テスト", "start": 0, "end": 5}]
        store._quick_analyze_all(segments)
        assert store.segments[0].id == "seg_000"

    def test_get_cache_key(self, store):
        """_get_cache_key: キャッシュキー生成"""
        segments = [{"text": "テスト"}]
        key = store._get_cache_key(segments)
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hex

    def test_get_cache_key_deterministic(self, store):
        """_get_cache_key: 同じ入力 → 同じキー"""
        segs = [{"text": "テスト"}]
        assert store._get_cache_key(segs) == store._get_cache_key(segs)

    def test_parse_fast_response_valid(self, store):
        """_parse_fast_response: 有効JSON"""
        text = '{"important": ["seg_001"], "telops": [{"id": "seg_001", "text": "テロップ"}]}'
        result = store._parse_fast_response(text)
        assert result["important"] == ["seg_001"]
        assert len(result["telops"]) == 1

    def test_parse_fast_response_invalid(self, store):
        """_parse_fast_response: 無効文字列 → 空"""
        result = store._parse_fast_response("This is not JSON")
        assert result["important"] == []
        assert result["telops"] == []

    def test_apply_ai_result(self, store):
        """_apply_ai_result: AI結果適用"""
        store._quick_analyze_all([
            {"id": "s1", "text": "テスト1", "start": 0, "end": 5},
            {"id": "s2", "text": "テスト2", "start": 5, "end": 10},
        ])
        ai_result = {
            "important": ["s1"],
            "telops": [{"id": "s2", "text": "短縮テロップ"}],
        }
        store._apply_ai_result(ai_result, [])
        assert store.segments[0].importance >= 0.8
        assert store.segments[0].highlight_candidate is True
        assert store.segments[1].telop_candidate is True
        assert store.segments[1].telop_suggestion == "短縮テロップ"

    def test_get_summary(self, store):
        """_get_summary: サマリー"""
        store._quick_analyze_all(_make_segments(3))
        summary = store._get_summary()
        assert summary["total_segments"] == 3
        assert "stats" in summary

    def test_get_telop_candidates(self, store):
        """get_telop_candidates: テロップ候補取得"""
        store._quick_analyze_all([
            {"id": "s1", "text": "大切", "start": 0, "end": 5},
            {"id": "s2", "text": "はい", "start": 5, "end": 6},
        ])
        candidates = store.get_telop_candidates()
        assert len(candidates) >= 1

    def test_save_and_load(self, store, tmp_path):
        """save / _load: 保存と読み込みの往復"""
        store._quick_analyze_all(_make_segments(3))
        save_path = tmp_path / "test_semantic.json"
        store.save(save_path)
        assert save_path.exists()

        # 新しいストアで読み込み
        from semantic_store import SemanticSubtitleStoreV2
        store2 = SemanticSubtitleStoreV2.__new__(SemanticSubtitleStoreV2)
        store2.store_path = save_path
        store2.segments = []
        store2.topics = []
        store2.key_moments = []
        store2.metadata = {}
        store2.stats = {"api_calls": 0, "cache_hits": 0, "fallbacks": 0}
        store2.client = MagicMock()
        store2.model = "test"
        store2._load()
        assert len(store2.segments) == 3

    def test_save_no_path_raises(self, store):
        """save: パスなし → ValueError"""
        store.store_path = None
        with pytest.raises(ValueError):
            store.save()

    def test_enhance_with_ai_fallback(self, store):
        """_enhance_with_ai: APIError 発生時に fallback カウントされること"""
        from google.genai.errors import APIError
        store._quick_analyze_all(_make_segments(3))
        store.client.models.generate_content.side_effect = APIError("API Error", 500, "{}")
        
        with patch("semantic_store.USE_CACHE", False):
            store._enhance_with_ai(_make_segments(3))
        
        assert store.stats["fallbacks"] == 1

    def test_enhance_with_ai_fallback_valueerror(self, store):
        """_enhance_with_ai: ValueError 発生時に fallback カウントされること"""
        store._quick_analyze_all(_make_segments(3))
        store.client.models.generate_content.side_effect = ValueError("Value Error")
        
        with patch("semantic_store.USE_CACHE", False):
            store._enhance_with_ai(_make_segments(3))
        
        assert store.stats["fallbacks"] == 1

    def test_enhance_with_ai_fallback_typeerror(self, store):
        """_enhance_with_ai: TypeError 発生時に fallback カウントされること"""
        store._quick_analyze_all(_make_segments(3))
        store.client.models.generate_content.side_effect = TypeError("Type Error")
        
        with patch("semantic_store.USE_CACHE", False):
            store._enhance_with_ai(_make_segments(3))
        
        assert store.stats["fallbacks"] == 1

    def test_enhance_with_ai_fallback_attributeerror(self, store):
        """_enhance_with_ai: AttributeError 発生時に fallback カウントされること"""
        store._quick_analyze_all(_make_segments(3))
        store.client.models.generate_content.side_effect = AttributeError("Attribute Error")
        
        with patch("semantic_store.USE_CACHE", False):
            store._enhance_with_ai(_make_segments(3))
        
        assert store.stats["fallbacks"] == 1

    def test_get_key_moments_empty(self, store):
        """get_key_moments: 空の場合"""
        moments = store.get_key_moments()
        assert moments == []

    def test_get_topics_empty(self, store):
        """get_topics: 空の場合"""
        topics = store.get_topics()
        assert topics == []

    # ============================================================
    # ロバストネス・カオス耐性追加テスト
    # ============================================================

    def test_validate_and_sanitize_segments_malformed(self, store):
        """不正なデータが入力された場合のバリデーションとサニタイズ検証"""
        malformed_inputs = [
            None,  # 辞書ではない
            {"id": 123, "text": None, "start": "1.5", "end": "abc"},  # 不正な型
            {"text": "正常テキスト"}  # id や時間欠損
        ]
        
        sanitized = store._validate_and_sanitize_segments(malformed_inputs)
        
        # 辞書ではないNoneはスキップされるので2要素残るはず
        assert len(sanitized) == 2
        
        # 1つ目の要素のサニタイズ結果
        assert sanitized[0]["id"] == "123"
        assert sanitized[0]["text"] == ""
        assert sanitized[0]["start"] == 1.5
        assert sanitized[0]["end"] == 0.0  # abc は 0.0 にフォールバック
        
        # 2つ目の要素のサニタイズ結果
        assert sanitized[1]["id"] == "seg_002"  # 自動連番ID (インデックス2に相当するためseg_002になる)
        assert sanitized[1]["text"] == "正常テキスト"
        assert sanitized[1]["start"] == 0.0
        assert sanitized[1]["end"] == 0.0

    def test_load_missing_file(self, store, tmp_path):
        """存在しないファイルを _load しようとした場合に安全に無視されること"""
        store.store_path = tmp_path / "does_not_exist.json"
        
        # 例外が発生せず、空データで初期化されること
        store._load()
        assert store.segments == []
        assert store.metadata == {}

    def test_load_corrupted_json(self, store, tmp_path):
        """破損したJSONファイルを _load しようとした場合に安全にフォールバックすること"""
        corrupted_file = tmp_path / "corrupted.json"
        with open(corrupted_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json [")
            
        store.store_path = corrupted_file
        
        # 例外が発生せず、空データで初期化されること
        store._load()
        assert store.segments == []
        assert store.metadata == {}

    def test_get_cached_result_corrupted_json(self, store, tmp_path):
        """破損したキャッシュファイルを読み込もうとした場合に削除されること"""
        cache_key = "corrupted_test_key"
        cache_file = store.cache_dir / f"{cache_key}.json"
        
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write("{ bad cache data }")
            
        assert cache_file.exists()
        
        # USE_CACHEはデフォルトでTrue
        result = store._get_cached_result(cache_key)
            
        # 破損キャッシュのため None が返り、ファイルが削除されていること
        assert result is None
        assert not cache_file.exists()

    def test_save_atomic_success(self, store, tmp_path):
        """正常にアトミック保存され、ファイルが作成されること"""
        store._quick_analyze_all(_make_segments(2))
        save_path = tmp_path / "atomic_success.json"
        
        store.save(save_path)
        assert save_path.exists()
        
        with open(save_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["segments"]) == 2

    def test_save_atomic_failure_retains_original(self, store, tmp_path):
        """保存途中でエラーが起きた場合に、元のファイルが保護されること"""
        save_path = tmp_path / "original.json"
        
        # 初期状態のファイルを保存
        store._quick_analyze_all(_make_segments(2))
        store.save(save_path)
        assert save_path.exists()
        original_mtime = save_path.stat().st_mtime
        
        # json.dump でエラーを強制注入するモック
        with patch("json.dump", side_effect=IOError("Disk Full")):
            with pytest.raises(IOError):
                store.save(save_path)
                
        # ディスクフルエラー発生後も、元のファイルが壊れず残っていること
        assert save_path.exists()
        assert save_path.stat().st_mtime == original_mtime
        
        with open(save_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["segments"]) == 2

    def test_parse_fast_response_malformed_structure(self, store):
        """高速分析のJSON構造が想定外の型の場合にクラッシュせずフォールバックされること"""
        # important がリストではなく整数、telops がリストではなく辞書
        malformed_json_text = '{"important": 123, "telops": {"id": "seg_001", "text": "bad_type"}}'
        
        result = store._parse_fast_response(malformed_json_text)
        assert result["important"] == []
        assert result["telops"] == []
        
        # telops の要素に id や text が欠けている場合
        missing_keys_json = '{"important": ["seg_001"], "telops": [{"text": "only text"}]}'
        result = store._parse_fast_response(missing_keys_json)
        assert result["important"] == ["seg_001"]
        assert result["telops"] == []

    # ============================================================
    # 追加カバレッジテスト (Phase 27 改善)
    # ============================================================

    def test_store_init_normal(self, tmp_path):
        """__init__: 正常初期化の検証（キャッシュディレクトリ自動生成を含む）"""
        from semantic_store import SemanticSubtitleStoreV2
        save_path = tmp_path / "test_store.json"
        cache_dir = tmp_path / "test_cache"
        
        # モックGeminiクライアントを設定した状態で初期化を実行
        with patch("semantic_store.get_gemini_client") as mock_client,              patch("semantic_store.get_model", return_value="gemini-test"):
            mock_client.return_value = MagicMock()
            store = SemanticSubtitleStoreV2(store_path=save_path, cache_dir=cache_dir)
            
            assert store.store_path == save_path
            assert store.cache_dir == cache_dir
            assert cache_dir.exists()

    def test_store_init_cache_mkdir_error(self, tmp_path):
        """__init__: キャッシュディレクトリ作成でOSErrorが発生した場合に警告されること"""
        from semantic_store import SemanticSubtitleStoreV2
        cache_dir = tmp_path / "test_cache"
        
        with patch("semantic_store.get_gemini_client") as mock_client,              patch("semantic_store.get_model", return_value="gemini-test"),              patch("pathlib.Path.mkdir", side_effect=OSError("Permission Denied")):
            mock_client.return_value = MagicMock()
            
            # 例外がスローされず、処理が継続することを確認
            store = SemanticSubtitleStoreV2(cache_dir=cache_dir)
            assert store.cache_dir == cache_dir

    def test_get_cached_result_success(self, store, tmp_path):
        """_get_cached_result / _save_to_cache: キャッシュ保存とヒットの検証"""
        store.cache_dir = tmp_path / "cache"
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_key = "test_key_123"
        result_data = {"important": ["seg_000"], "telops": []}
        
        # キャッシュ保存
        store._save_to_cache(cache_key, result_data)
        
        # キャッシュ取得
        cached = store._get_cached_result(cache_key)
        assert cached == result_data
        assert store.stats["cache_hits"] == 1

    def test_get_cached_result_os_error(self, store, tmp_path):
        """_get_cached_result: キャッシュ読み込み時にOSErrorが発生した場合のフォールバック"""
        store.cache_dir = tmp_path / "cache"
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_key = "os_error_key"
        cache_file = store.cache_dir / f"{cache_key}.json"
        cache_file.write_text("{}", encoding="utf-8")
        
        # open をモックして OSError をスローさせる
        with patch("builtins.open", side_effect=OSError("Read error")):
            result = store._get_cached_result(cache_key)
            assert result is None

    def test_save_to_cache_os_error(self, store, tmp_path):
        """_save_to_cache: キャッシュ保存時にOSErrorが発生した場合の安全処理"""
        store.cache_dir = tmp_path / "cache"
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # tempfile.mkstemp で OSError を発生させる
        with patch("tempfile.mkstemp", side_effect=OSError("Disk write error")):
            # 例外が伝播せずにログ出力されることを確認
            store._save_to_cache("error_key", {"data": 1})

    def test_load_os_error(self, store, tmp_path):
        """_load: ファイル読み込み時にOSErrorが発生した場合の安全フォールバック"""
        store.store_path = tmp_path / "test_store.json"
        
        with patch("builtins.open", side_effect=OSError("Disk Read Error")):
            # 例外が起きずに安全に空データで初期化されること
            store._load()
            assert store.segments == []

    def test_save_os_error(self, store, tmp_path):
        """save: 保存時にOSErrorが発生した場合に正しく例外が発生すること"""
        save_path = tmp_path / "error_store.json"
        store._quick_analyze_all(_make_segments(2))
        
        with patch("tempfile.mkstemp", side_effect=OSError("Write permission error")):
            with pytest.raises(OSError):
                store.save(save_path)

    def test_analyze_with_mock_ai(self, store, tmp_path):
        """analyze: AIモック結果が正しく適用される正常系検証"""
        store.cache_dir = tmp_path / "cache"
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        
        segments = _make_segments(3)
        
        # Gemini API のレスポンスをモック
        mock_response = MagicMock()
        mock_response.text = '{"important": ["seg_001"], "telops": [{"id": "seg_001", "text": "AIテロップ"}]}'
        store.client.models.generate_content.return_value = mock_response
        
        summary = store.analyze(segments)
        
        # 統計と結果の検証
        assert summary["total_segments"] == 3
        assert store.stats["api_calls"] == 1
        assert store.segments[1].importance >= 0.8
        assert store.segments[1].telop_candidate is True
        assert store.segments[1].telop_suggestion == "AIテロップ"

    def test_analyze_with_ai_batched(self, store, tmp_path):
        """analyze: バッチサイズ（30）を超えるセグメントが入力された場合のバッチ分割処理検証"""
        store.cache_dir = tmp_path / "cache"
        
        # 35件のセグメントを用意
        segments = _make_segments(35)
        
        mock_response = MagicMock()
        mock_response.text = '{"important": [], "telops": []}'
        store.client.models.generate_content.return_value = mock_response
        
        summary = store.analyze(segments)
        
        # 35件が処理され、APIが2回（バッチサイズ30のため 30+5=2回）呼び出されたことを検証
        assert summary["total_segments"] == 35
        assert store.stats["api_calls"] == 2

    def test_create_semantic_store_factory(self, tmp_path):
        """create_semantic_store: ファクトリ関数による一連の動作（作成・分析・保存）の検証"""
        from semantic_store import create_semantic_store
        
        save_path = tmp_path / "factory_store.json"
        cache_dir = tmp_path / "factory_cache"
        segments = _make_segments(3)
        
        mock_response = MagicMock()
        mock_response.text = '{"important": [], "telops": []}'
        
        with patch("semantic_store.get_gemini_client") as mock_client,              patch("semantic_store.get_model", return_value="gemini-test"):
            client = MagicMock()
            client.models.generate_content.return_value = mock_response
            mock_client.return_value = client
            
            # ファクトリ関数の呼び出し
            # パッチ適用により __init__ は cache_dir を受け取れるが、create_semantic_store は
            # store = SemanticSubtitleStoreV2(store_path) を呼び出しているので、
            # cache_dir のオーバーライドが必要な場合は store_path を元に動作
            store = create_semantic_store(segments, store_path=save_path)
            
            assert save_path.exists()
            assert len(store.segments) == 3

    # ============================================================
    # 追加カバレッジテスト (カバレッジ 100% 化)
    # ============================================================

    def test_parse_fast_response_corrupted_json(self, store):
        """_parse_fast_response: 中カッコはあるがJSONとしてパースできない場合"""
        result = store._parse_fast_response("{invalid_json}")
        assert result["important"] == []
        assert result["telops"] == []

    def test_parse_fast_response_unexpected_exception(self, store):
        """_parse_fast_response: json.loadsで予期せぬ例外が発生した場合"""
        with patch("json.loads", side_effect=TypeError("Unexpected mock type error")):
            result = store._parse_fast_response('{"important": []}')
            assert result["important"] == []
            assert result["telops"] == []

    def test_validate_and_sanitize_segments_not_list(self, store):
        """_validate_and_sanitize_segments: リスト以外のデータが渡された場合"""
        result = store._validate_and_sanitize_segments({"not": "a list"})
        assert result == []

    def test_validate_and_sanitize_segments_invalid_start_end(self, store):
        """_validate_and_sanitize_segments: start, end が float キャストできない場合"""
        bad_segments = [
            {"id": "seg_001", "text": "test", "start": "invalid_start", "end": "invalid_end"}
        ]
        result = store._validate_and_sanitize_segments(bad_segments)
        assert len(result) == 1
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.0

    def test_save_to_cache_not_using_cache(self, store, tmp_path):
        """_save_to_cache: USE_CACHEがFalseの場合"""
        store.cache_dir = tmp_path / "cache"
        with patch("semantic_store.USE_CACHE", False):
            # 何も書き込まれず終了すること
            store._save_to_cache("some_key", {"data": 1})
            assert not (store.cache_dir / "some_key.json").exists()

    def test_load_no_store_path(self, store):
        """_load: store_pathがNoneの場合"""
        store.store_path = None
        store._load()
        assert store.segments == []

    def test_save_to_cache_mkdir_os_error(self, store, tmp_path):
        """_save_to_cache: mkdirでOSErrorが発生した場合"""
        store.cache_dir = tmp_path / "cache_error"
        with patch("pathlib.Path.mkdir", side_effect=OSError("Perm Denied")):
            store._save_to_cache("key", {"data": 1})
            assert not store.cache_dir.exists()

    def test_save_to_cache_remove_os_error(self, store, tmp_path):
        """_save_to_cache: tempfile作成失敗後の一時ファイル削除でもOSErrorが発生する場合"""
        store.cache_dir = tmp_path / "cache"
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # mkstempは成功させるが、その後の書き込み（json.dumpなど）でOSErrorを発生させる。
        # これにより tmp_path が割り当てられ、exceptブロックに到達する。
        dummy_fd = 999
        dummy_path = str(store.cache_dir / "dummy.tmp")
        
        with patch("tempfile.mkstemp", return_value=(dummy_fd, dummy_path)),              patch("os.fdopen", side_effect=OSError("write error")),              patch("os.path.exists", return_value=True),              patch("os.remove", side_effect=OSError("remove error")):
            store._save_to_cache("key", {"data": 1}) # 例外が発生せず処理されること

    def test_save_remove_os_error(self, store, tmp_path):
        """save: 保存失敗時の一時ファイル削除でOSErrorが発生する場合"""
        save_path = tmp_path / "store.json"
        store._quick_analyze_all(_make_segments(2))
        
        dummy_fd = 999
        dummy_path = str(tmp_path / "dummy.tmp")
        
        with patch("tempfile.mkstemp", return_value=(dummy_fd, dummy_path)),              patch("os.fdopen", side_effect=OSError("write error")),              patch("os.path.exists", return_value=True),              patch("os.remove", side_effect=OSError("remove error")):
            with pytest.raises(OSError):
                store.save(save_path)

    def test_get_cached_result_unlink_os_error(self, store, tmp_path):
        """_get_cached_result: 破損キャッシュファイルの削除でOSErrorが発生する場合"""
        store.cache_dir = tmp_path / "cache"
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = "corrupted_key"
        cache_file = store.cache_dir / f"{cache_key}.json"
        cache_file.write_text("{bad json}", encoding="utf-8")
        
        with patch("pathlib.Path.unlink", side_effect=OSError("unlink error")):
            result = store._get_cached_result(cache_key)
            assert result is None

    def test_analyze_with_cache_hit(self, store, tmp_path):
        """analyze: キャッシュヒット時の挙動検証"""
        store.cache_dir = tmp_path / "cache"
        store.cache_dir.mkdir(parents=True, exist_ok=True)
        
        segments = [{"id": "seg_001", "text": "本質的なポイント", "start": 0.0, "end": 1.5}]
        cache_key = store._get_cache_key(segments)
        
        # キャッシュデータを保存しておく
        cache_data = {
            "important": ["seg_001"],
            "telops": [{"id": "seg_001", "text": "本質"}]
        }
        store._save_to_cache(cache_key, cache_data)
        
        # analyzeを実行（APIは呼ばれずにキャッシュヒットする）
        summary = store.analyze(segments)
        
        assert store.stats["cache_hits"] == 1
        assert store.stats["api_calls"] == 0
        assert store.segments[0].importance == 0.8
        assert store.segments[0].telop_candidate is True
        assert store.segments[0].telop_suggestion == "本質"

    def test_atomic_write_json_fd_leak_on_error(self, store, tmp_path):
        """_atomic_write_json: json.dump時等に例外が発生した場合にfdが確実に閉じられ、ファイルが削除されること"""
        save_path = tmp_path / "leak_test.json"
        store._quick_analyze_all([{"id": "seg_001", "text": "test"}])
        
        # json.dump で例外を発生させる
        with patch("json.dump", side_effect=ValueError("Dump Error")):
            with pytest.raises(ValueError):
                store.save(save_path)
                
        # 例外発生後に一時ファイルが残っておらず、かつfdが閉じられているため
        # 同一パスへの再書き込みや削除がPermissionErrorにならずに行えること
        # (特にWindows上でのロック解放を検証)
        assert not save_path.exists()
        
        # 一時ファイル用ディレクトリがクリーンであること（.tmpファイルが残っていない）
        temp_dir = save_path.parent
        tmp_files = list(temp_dir.glob("sem_*.tmp"))
        assert len(tmp_files) == 0

