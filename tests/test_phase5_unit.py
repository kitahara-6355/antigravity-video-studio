"""
Phase 5: Semantic Archive Search - ユニットテスト
pytest ベースの9項目テスト

テスト対象:
1. tag_for_search   - 各フィールドの組み合わせ
2. STUBベクトル     - 決定論的・語順考慮性
3. build_index      - モックアセットでのインデックス構築
4. rebuild_index    - 全面再構築の上書き動作
5. search           - コサイン類似度の降順ソート
6. search空インデックス - 空リスト返却
7. API build-index  - HTTPレスポンス確認
8. API search       - JSONレスポンス構造確認
9. API index-stats  - 統計情報取得
"""
import sys
import os
import math
from pathlib import Path

# backend をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.environ["GOOGLE_API_KEY"] = "dummy_key_for_stub_mode"

import pytest
from asset_library import AssetEntry, CreativeAssetLibrary
from services.vector_search import VectorSearchEngine


# ===========================================================================
# テスト用フィクスチャ
# ===========================================================================

@pytest.fixture
def fresh_engine(tmp_path):
    """毎テストで新しい VectorSearchEngine インスタンス（一時ディレクトリ使用）"""
    import services.vector_search as vs_module
    original_chroma_dir = vs_module.CHROMA_DIR
    vs_module.CHROMA_DIR = tmp_path / "test_chroma_db"
    engine = VectorSearchEngine()
    yield engine
    vs_module.CHROMA_DIR = original_chroma_dir


@pytest.fixture
def sample_assets():
    """テスト用のモックアセット3件"""
    return [
        AssetEntry(
            id="a001", path="channel_owner/photos/portrait_001.jpg",
            filename="portrait_001.jpg", type="photo", category="channel_owner",
            labels=["portrait", "人物"], style_tags=["professional"],
            colors=["#1A1A1A", "#FFFFFF"], mood="professional",
            usage_for=["thumbnail", "profile"]
        ),
        AssetEntry(
            id="a002", path="brand/logos/logo_main.png",
            filename="logo_main.png", type="logo", category="brand",
            labels=["logo"], style_tags=["modern"],
            colors=["#FF6B00"], mood="energetic",
            usage_for=["opening", "thumbnail"]
        ),
        AssetEntry(
            id="a003", path="brand/music/bgm_warm.mp3",
            filename="bgm_warm.mp3", type="audio", category="brand",
            labels=["BGM", "音楽"], style_tags=["calm"],
            colors=["#FFA500"], mood="warm",
            usage_for=["insert"]
        ),
    ]


@pytest.fixture
def asset_texts(sample_assets):
    """tag_for_search を用いたインデックス用テキストリスト"""
    lib = CreativeAssetLibrary.__new__(CreativeAssetLibrary)
    lib.assets = sample_assets
    lib.guests = {}
    return [
        {
            "asset_id": a.id,
            "text": lib.tag_for_search(a),
            "metadata": {"filename": a.filename, "type": a.type, "category": a.category}
        }
        for a in sample_assets
    ]


# ===========================================================================
# Test 1: tag_for_search
# ===========================================================================

class TestTagForSearch:
    """tag_for_search が正しいテキストサマリを生成する"""

    def _make_lib(self):
        lib = CreativeAssetLibrary.__new__(CreativeAssetLibrary)
        lib.assets = []
        lib.guests = {}
        return lib

    def test_includes_filename(self, sample_assets):
        """ファイル名がサマリに含まれる"""
        lib = self._make_lib()
        result = lib.tag_for_search(sample_assets[0])
        assert "portrait_001.jpg" in result

    def test_includes_labels(self, sample_assets):
        """ラベルがサマリに含まれる"""
        lib = self._make_lib()
        result = lib.tag_for_search(sample_assets[0])
        assert "portrait" in result or "人物" in result

    def test_includes_color_name(self, sample_assets):
        """HEXカラーが色名に変換されてサマリに含まれる（#FFA500 → オレンジ or 暖色系）"""
        lib = self._make_lib()
        result = lib.tag_for_search(sample_assets[2])  # #FFA500
        assert "オレンジ" in result or "暖色系" in result or "色" in result

    def test_includes_series_theme(self, sample_assets):
        """シリーズテーマが付与された場合にサマリに含まれる"""
        lib = self._make_lib()
        result = lib.tag_for_search(sample_assets[0], series_theme="書道の世界")
        assert "書道の世界" in result

    def test_neutral_mood_excluded(self, sample_assets):
        """mood が 'neutral' の場合はサマリに含まれない"""
        lib = self._make_lib()
        asset = AssetEntry(
            id="a999", path="test.jpg", filename="test.jpg",
            type="photo", category="other", mood="neutral"
        )
        result = lib.tag_for_search(asset)
        assert "neutral" not in result

    def test_empty_lists_excluded(self):
        """空のラベル/スタイルはサマリに含まれない"""
        lib = CreativeAssetLibrary.__new__(CreativeAssetLibrary)
        lib.assets = []
        lib.guests = {}
        asset = AssetEntry(
            id="a998", path="empty.jpg", filename="empty.jpg",
            type="photo", category="other"
        )
        result = lib.tag_for_search(asset)
        assert "ラベル:" not in result
        assert "スタイル:" not in result


# ===========================================================================
# Test 2: STUB Embedding
# ===========================================================================

class TestStubEmbedding:
    """STUB モードの Embedding ベクトル品質テスト"""

    def test_determinism(self, fresh_engine):
        """同一テキストは毎回同一ベクトルを返す"""
        text = "プロフェッショナルな人物写真"
        vec1 = fresh_engine._stub_embedding(text)
        vec2 = fresh_engine._stub_embedding(text)
        assert vec1 == vec2

    def test_order_sensitivity(self, fresh_engine):
        """語順が異なればベクトルが異なる（重要!）"""
        text_a = "プロフェッショナルな人物写真"
        text_b = "人物写真なプロフェッショナル"
        vec_a = fresh_engine._stub_embedding(text_a)
        vec_b = fresh_engine._stub_embedding(text_b)
        assert vec_a != vec_b, "語順が違うのに同じベクトルになってはいけません"

    def test_dimension(self, fresh_engine):
        """ベクトルの次元数が EMBEDDING_DIM と一致する"""
        from services.vector_search import EMBEDDING_DIM
        vec = fresh_engine._stub_embedding("test")
        assert len(vec) == EMBEDDING_DIM

    def test_normalized(self, fresh_engine):
        """ベクトルが L2 正規化されている（ノルム ≈ 1.0）"""
        vec = fresh_engine._stub_embedding("テスト")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6


# ===========================================================================
# Test 3 & 4: インデックス構築
# ===========================================================================

class TestBuildIndex:
    """build_index と rebuild_index のテスト"""

    def test_build_index_basic(self, fresh_engine, asset_texts):
        """3件のアセットでインデックスが構築される"""
        result = fresh_engine.build_index(asset_texts)
        assert result["success"] is True
        assert result["new_entries"] == 3
        assert result["total_entries"] == 3

    def test_build_index_incremental(self, fresh_engine, asset_texts):
        """同じデータを2回 build_index しても重複しない"""
        fresh_engine.build_index(asset_texts)
        result = fresh_engine.build_index(asset_texts)
        assert result["new_entries"] == 0  # 差分更新：新規なし
        assert result["total_entries"] == 3

    def test_rebuild_index_overwrites(self, fresh_engine, asset_texts):
        """rebuild_index は既存データを上書きする"""
        fresh_engine.build_index(asset_texts)
        assert fresh_engine.get_index_stats()["total_entries"] == 3

        # 1件だけで再構築
        single_item = [asset_texts[0]]
        result = fresh_engine.rebuild_index(single_item)
        assert result["success"] is True
        assert result["total_entries"] == 1
        assert fresh_engine.get_index_stats()["total_entries"] == 1

    def test_build_index_empty(self, fresh_engine):
        """空のリストを渡した場合は失敗を返す"""
        result = fresh_engine.build_index([])
        assert result["success"] is False

    def test_build_index_mode_field(self, fresh_engine, asset_texts):
        """build_index は mode='incremental' を返す"""
        result = fresh_engine.build_index(asset_texts)
        assert result.get("mode") == "incremental"

    def test_rebuild_index_mode_field(self, fresh_engine, asset_texts):
        """rebuild_index は mode='rebuild' を返す"""
        result = fresh_engine.rebuild_index(asset_texts)
        assert result.get("mode") == "rebuild"


# ===========================================================================
# Test 5 & 6: 自然言語検索
# ===========================================================================

class TestSearch:
    """search メソッドのテスト"""

    def test_search_returns_sorted_by_score(self, fresh_engine, asset_texts):
        """検索結果がコサイン類似度の降順になっている"""
        fresh_engine.build_index(asset_texts)
        results = fresh_engine.search("人物写真", top_k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_empty_index_returns_empty(self, fresh_engine):
        """インデックスが空の場合は空リストを返す"""
        results = fresh_engine.search("テスト")
        assert results == []

    def test_search_top_k_limit(self, fresh_engine, asset_texts):
        """top_k 件数を超えない"""
        fresh_engine.build_index(asset_texts)
        results = fresh_engine.search("写真", top_k=2)
        assert len(results) <= 2

    def test_search_result_fields(self, fresh_engine, asset_texts):
        """SearchResult に必要なフィールドが揃っている"""
        fresh_engine.build_index(asset_texts)
        results = fresh_engine.search("BGM", top_k=1)
        if results:
            r = results[0]
            assert hasattr(r, "asset_id")
            assert hasattr(r, "score")
            assert hasattr(r, "text_summary")
            assert hasattr(r, "metadata")


# ===========================================================================
# Test 7, 8, 9: FastAPI エンドポイント
# ===========================================================================

class TestAPIEndpoints:
    """FastAPI のエンドポイントテスト"""

    @pytest.fixture
    def client(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.youtube_optimizer import router
        import services.vector_search as vs_module
        
        # 一時ディレクトリを CHROMA_DIR に設定し、新しい VectorSearchEngine インスタンスを生成して差し替える
        original_chroma_dir = vs_module.CHROMA_DIR
        vs_module.CHROMA_DIR = tmp_path / "test_chroma_db_api"
        
        original_engine = vs_module.vector_search_engine
        vs_module.vector_search_engine = vs_module.VectorSearchEngine()
        
        app = FastAPI()
        app.include_router(router)
        
        yield TestClient(app)
        
        # テスト終了後に元に戻す
        vs_module.CHROMA_DIR = original_chroma_dir
        vs_module.vector_search_engine = original_engine


    def test_api_index_stats(self, client):
        """GET /api/youtube/assets/index-stats が 200 と正しい構造を返す"""
        res = client.get("/api/youtube/assets/index-stats")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "total_entries" in data
        assert "index_exists" in data

    def test_api_build_index(self, client):
        """POST /api/youtube/assets/build-index が 200 と success フィールドを返す"""
        res = client.post("/api/youtube/assets/build-index")
        assert res.status_code == 200
        data = res.json()
        assert "success" in data

    def test_api_build_index_force_rebuild(self, client):
        """POST /api/youtube/assets/build-index?force_rebuild=true が動作する"""
        res = client.post("/api/youtube/assets/build-index?force_rebuild=true")
        assert res.status_code == 200

    def test_api_search_basic(self, client):
        """GET /api/youtube/assets/search?q=... が 200 と正しい構造を返す"""
        res = client.get("/api/youtube/assets/search?q=プロフェッショナル&top_k=3")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "query" in data
        assert "count" in data
        assert "results" in data
        assert "index_stats" in data
        assert data["query"] == "プロフェッショナル"

    def test_api_search_missing_query(self, client):
        """GET /api/youtube/assets/search （q なし）が 400 を返す"""
        res = client.get("/api/youtube/assets/search")
        # FastAPI のパラメータ検証で 422 または、空文字なら 400
        assert res.status_code in (400, 422)

    def test_api_health(self, client):
        """GET /api/youtube/health が ok を返す"""
        res = client.get("/api/youtube/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


# ===========================================================================
# Test 10: カバレッジ・堅牢性エッジケース
# ===========================================================================

class TestVectorSearchCoverageEdgeCases:
    """カバレッジと入力検証、例外処理などのエッジケーステスト"""

    def test_build_index_empty_fields(self, fresh_engine):
        """asset_id または text が空のアセットはスキップされる"""
        asset_texts = [
            {"asset_id": "", "text": "有効なテキスト", "metadata": {}},
            {"asset_id": "a001", "text": "", "metadata": {}},
            {"asset_id": "a002", "text": "有効なアセット", "metadata": {}}
        ]
        result = fresh_engine.build_index(asset_texts)
        assert result["success"] is True
        assert result["new_entries"] == 1
        assert result["total_entries"] == 1
        assert fresh_engine.get_index_stats()["total_entries"] == 1

    def test_rebuild_index_empty(self, fresh_engine):
        """rebuild_index に空リストを渡した場合、早期リターンで success=False を返す"""
        result = fresh_engine.rebuild_index([])
        assert result["success"] is False
        assert "素材がありません" in result["message"]

    def test_stub_embedding_fallback_no_api_key(self, fresh_engine):
        """GOOGLE_API_KEY が未設定の時、ダミー Embedding に安全にフォールバックする"""
        import os
        orig_key = os.environ.get("GOOGLE_API_KEY")
        if "GOOGLE_API_KEY" in os.environ:
            del os.environ["GOOGLE_API_KEY"]
        
        try:
            # factory をリセットして GOOGLE_API_KEY の変更を反映させる
            from gemini_client_factory import reset_client
            reset_client()
            
            # クライアントが None を返し、STUB ベクトルが使われることを確認
            vec = fresh_engine._get_embedding("テスト")
            assert len(vec) == 768
        finally:
            if orig_key is not None:
                os.environ["GOOGLE_API_KEY"] = orig_key
            from gemini_client_factory import reset_client
            reset_client()

    def test_search_invalid_top_k(self, fresh_engine, asset_texts):
        """top_k が 0 以下の場合は安全に空のリストを返す"""
        fresh_engine.build_index(asset_texts)
        results = fresh_engine.search("テスト", top_k=0)
        assert results == []
        results_neg = fresh_engine.search("テスト", top_k=-1)
        assert results_neg == []

    def test_score_clipping(self, fresh_engine, asset_texts):
        """コサイン距離が極端な値の場合でも類似度スコアが 0.0〜1.0 にクリップされる"""
        from unittest.mock import patch
        fresh_engine.build_index(asset_texts)
        
        # mock collection の query 応答をパッチ
        # distance = 2.0 (コサイン類似度 = -1.0) のとき、score は 0.0 になること
        # distance = -0.5 (コサイン類似度 = 1.5) のとき、score は 1.0 になること
        mock_results = {
            "ids": [["a001", "a002"]],
            "distances": [[2.0, -0.5]],
            "documents": [["text1", "text2"]],
            "metadatas": [[{}, {}]]
        }
        
        with patch.object(fresh_engine._collection, "query", return_value=mock_results):
            results = fresh_engine.search("クエリ", top_k=2)
            assert len(results) == 2
            assert results[0].score == 0.0  # 1.0 - 2.0 = -1.0 -> 0.0 にクリップ
            assert results[1].score == 1.0  # 1.0 - (-0.5) = 1.5 -> 1.0 にクリップ

    def test_metadata_safety_conversion(self, fresh_engine):
        """メタデータに多様な型が含まれていても安全に文字列などに標準化される"""
        asset_texts = [{
            "asset_id": "a001",
            "text": "テストテキスト",
            "metadata": {
                "int_val": 42,
                "float_val": 3.14,
                "bool_val": True,
                "none_val": None,
                "list_val": [1, 2, 3],
                "tuple_val": (4, 5)
            }
        }]
        result = fresh_engine.build_index(asset_texts)
        assert result["success"] is True
        
        # 登録されたメタデータの型が ChromaDB 許容型（str, int, float, bool）であることを検証
        stats = fresh_engine.get_index_stats()
        assert stats["total_entries"] == 1
        
        # collection から取得して検証
        stored = fresh_engine._collection.get()
        stored_meta = stored["metadatas"][0]
        assert stored_meta["int_val"] == 42
        assert stored_meta["float_val"] == 3.14
        assert stored_meta["bool_val"] is True
        assert stored_meta["none_val"] == ""
        assert stored_meta["list_val"] == "[1, 2, 3]"
        assert stored_meta["tuple_val"] == "(4, 5)"

    def test_genai_client_init_exception(self, fresh_engine):
        """genai.Client の初期化時に例外が発生した場合に安全に捕捉され STUB にフォールバックする"""
        from unittest.mock import patch
        
        # get_gemini_client が例外を投げるようにモックする
        fresh_engine._client_genai = None
        
        with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError("Init Error")):
            # _get_genai_client 内で例外がキャッチされ、None が返ることを確認
            client = fresh_engine._get_genai_client()
            assert client is None
            
            # _get_embedding も安全に STUB にフォールバックする
            vec = fresh_engine._get_embedding("テスト")
            assert len(vec) == 768

    def test_get_embedding_success(self, fresh_engine):
        """genai.Client が正常に Embedding を返した場合の処理"""
        from unittest.mock import MagicMock
        
        mock_client = MagicMock()
        mock_val = MagicMock()
        mock_val.values = [0.1] * 768
        mock_client.models.embed_content.return_value = MagicMock(embeddings=[mock_val])
        
        fresh_engine._client_genai = mock_client
        vec = fresh_engine._get_embedding("テスト")
        
        assert vec == [0.1] * 768
        mock_client.models.embed_content.assert_called_once_with(
            model="text-embedding-004",
            contents="テスト"
        )


    def test_init_with_existing_data(self, tmp_path):
        """既存データがある状態で初期化された場合の動作（カバレッジ補完）"""
        import services.vector_search as vs_module
        
        # 一時ディレクトリを保存先にする
        original_chroma_dir = vs_module.CHROMA_DIR
        vs_module.CHROMA_DIR = tmp_path / "test_chroma_db_init_existing"
        
        try:
            # 1. 最初のインスタンスを作ってデータを登録する
            engine1 = vs_module.VectorSearchEngine()
            asset_texts = [{
                "asset_id": "a001",
                "text": "テスト用アセットテキスト",
                "metadata": {"filename": "test.jpg"}
            }]
            result = engine1.build_index(asset_texts)
            assert result["success"] is True
            assert engine1._collection.count() == 1
            
            # 2. 同じ保存先で2つ目のインスタンスを作る（これにより count > 0 のログ出力ルートを通す）
            engine2 = vs_module.VectorSearchEngine()
            assert engine2._collection.count() == 1
        finally:
            vs_module.CHROMA_DIR = original_chroma_dir
