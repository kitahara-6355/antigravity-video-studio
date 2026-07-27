import sys
import os
import pytest
import sqlite3
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

# テスト実行時に競合しないよう、services.vector_search を再ロード可能にする
if 'services.vector_search' in sys.modules:
    del sys.modules['services.vector_search']

# ChromaDB をモック化する
mock_chroma_client = MagicMock()
mock_collection = MagicMock()
mock_collection.count.return_value = 0
mock_chroma_client.get_or_create_collection.return_value = mock_collection

# モジュールインポート時の singleton 作成のためにモックを適用
with patch('chromadb.PersistentClient', return_value=mock_chroma_client):
    from services.vector_search import vector_search_engine, SearchResult, COLLECTION_NAME, EMBEDDING_DIM, VectorSearchEngine

class TestVectorSearchEngine:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.engine = vector_search_engine
        
        # モックのリセット
        mock_chroma_client.reset_mock()
        mock_collection.reset_mock()
        
        # コレクションの再設定
        self.engine._collection = mock_collection
        mock_chroma_client.get_or_create_collection.return_value = mock_collection
        mock_chroma_client.create_collection.return_value = mock_collection
        
        # デフォルト値の設定
        mock_collection.count.return_value = 0
        mock_collection.count.side_effect = None
        mock_collection.get.return_value = {"ids": []}
        mock_collection.query.return_value = {
            "ids": [[]],
            "distances": [[]],
            "documents": [[]],
            "metadatas": [[]]
        }
        
        # 内部状態のリセット
        self.engine._client_genai = None
        self.engine._built_at = None

    def test_init_success(self):
        # コンストラクタをテストするために個別にインスタンス化する（モックのコンテキスト内）
        mock_collection.count.return_value = 5
        with patch('chromadb.PersistentClient', return_value=mock_chroma_client):
            engine = VectorSearchEngine()
            assert engine._chroma_client == mock_chroma_client
            assert engine._collection == mock_collection

    def test_get_genai_client_with_key(self):
        # GOOGLE_API_KEY が設定され、かつ正常にクライアントが生成される場合
        mock_client = MagicMock()
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "dummy_key"}), \
             patch('gemini_client_factory.get_gemini_client', return_value=mock_client):
            client = self.engine._get_genai_client()
            assert client == mock_client

    def test_get_genai_client_without_key(self):
        # GOOGLE_API_KEY が空の場合
        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}):
            client = self.engine._get_genai_client()
            assert client is None

    def test_get_genai_client_exception(self):
        # 例外発生時の挙動 (TD-533検証用)
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "dummy_key"}), \
             patch('gemini_client_factory.get_gemini_client', side_effect=ImportError("Failed to import genai")):
            client = self.engine._get_genai_client()
            assert client is None

    def test_get_embedding_success(self):
        # API経由で正常に Embedding を取得できる場合
        mock_client = MagicMock()
        mock_embedding_result = MagicMock()
        mock_embedding_result.embeddings = [MagicMock(values=[0.1] * EMBEDDING_DIM)]
        mock_client.models.embed_content.return_value = mock_embedding_result

        with patch.object(self.engine, '_get_genai_client', return_value=mock_client):
            vec = self.engine._get_embedding("hello")
            assert len(vec) == EMBEDDING_DIM
            assert vec[0] == 0.1

    def test_get_embedding_stub(self):
        # クライアントが None の場合にダミー Embedding にフォールバックすること
        with patch.object(self.engine, '_get_genai_client', return_value=None):
            vec = self.engine._get_embedding("hello")
            assert len(vec) == EMBEDDING_DIM
            # STUB ベクトルの規格化 (L2 Norm = 1.0) を検証
            norm = sum(v * v for v in vec)
            assert abs(norm - 1.0) < 1e-5

    def test_get_embedding_exception(self):
        # API呼び出しで例外が発生した場合にダミーにフォールバックすること (TD-534検証用)
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = RuntimeError("API limit exceeded")

        with patch.object(self.engine, '_get_genai_client', return_value=mock_client):
            vec = self.engine._get_embedding("hello")
            assert len(vec) == EMBEDDING_DIM
            norm = sum(v * v for v in vec)
            assert abs(norm - 1.0) < 1e-5

    def test_prepare_index_data(self):
        asset_texts = [
            # 正常なデータ
            {"asset_id": "asset_1", "text": "sample text", "metadata": {"category": "bgm", "duration": 30.5}},
            # 無効なデータ (IDなし)
            {"text": "no id text"},
            # 無効なデータ (テキストなし)
            {"asset_id": "asset_2"},
            # 特殊なメタデータ型 (None, リスト, 辞書)
            {"asset_id": "asset_3", "text": "special meta", "metadata": {"null_val": None, "list_val": [1, 2], "bool_val": True}},
            # 空のメタデータ
            {"asset_id": "asset_4", "text": "empty meta", "metadata": {}}
        ]

        # フィルタID指定あり
        filter_ids = {"asset_1"}

        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            ids, embeddings, documents, metadatas = self.engine._prepare_index_data(asset_texts, filter_ids=filter_ids)

            # asset_1 はフィルタされ、無効な行も除外されるため、asset_3 と asset_4 が登録されるはず
            assert ids == ["asset_3", "asset_4"]
            assert len(embeddings) == 2
            assert documents == ["special meta", "empty meta"]
            
            # メタデータの変換チェック
            # None は "", list は str([1, 2]), bool はそのまま保持
            assert metadatas[0]["null_val"] == ""
            assert metadatas[0]["list_val"] == "[1, 2]"
            assert metadatas[0]["bool_val"] is True
            # 空のメタデータはデフォルトキーにフォールバック
            assert metadatas[1] == {"is_empty_meta": "true"}

    def test_build_index_empty(self):
        res = self.engine.build_index([])
        assert res["success"] is False
        assert "ありません" in res["message"]

    def test_build_index_success(self):
        mock_collection.count.side_effect = [0, 2] # 既存0件、追加後2件
        mock_collection.get.return_value = {"ids": []}

        asset_texts = [
            {"asset_id": "a1", "text": "text1", "metadata": {}},
            {"asset_id": "a2", "text": "text2", "metadata": {}}
        ]

        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            res = self.engine.build_index(asset_texts)
            assert res["success"] is True
            assert res["new_entries"] == 2
            assert res["total_entries"] == 2
            mock_collection.add.assert_called_once()

    def test_build_index_duplicate(self):
        mock_collection.count.side_effect = [2, 2] # 既存2件、追加後も2件（重複で追加なし）
        mock_collection.get.return_value = {"ids": ["a1", "a2"]}

        asset_texts = [
            {"asset_id": "a1", "text": "text1", "metadata": {}}
        ]

        res = self.engine.build_index(asset_texts)
        assert res["success"] is True
        assert res["new_entries"] == 0
        assert res["total_entries"] == 2
        mock_collection.add.assert_not_called()

    def test_rebuild_index_empty(self):
        res = self.engine.rebuild_index([])
        assert res["success"] is False
        assert "ありません" in res["message"]

    def test_rebuild_index_success(self):
        mock_collection.count.side_effect = [3, 2] # 既存3件、再構築後2件
        
        asset_texts = [
            {"asset_id": "a1", "text": "text1", "metadata": {}},
            {"asset_id": "a2", "text": "text2", "metadata": {}}
        ]

        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            res = self.engine.rebuild_index(asset_texts)
            assert res["success"] is True
            assert res["new_entries"] == 2
            assert res["total_entries"] == 2
            mock_chroma_client.delete_collection.assert_called_once_with(COLLECTION_NAME)
            mock_collection.add.assert_called_once()

    def test_search_invalid_top_k(self):
        res = self.engine.search("query", top_k=0)
        assert res == []

    def test_search_empty_index(self):
        mock_collection.count.return_value = 0
        res = self.engine.search("query")
        assert res == []

    def test_search_success(self):
        mock_collection.count.return_value = 5
        
        # ChromaDB 検索結果のモック
        mock_collection.query.return_value = {
            "ids": [["a1", "a2"]],
            "distances": [[0.2, 0.9]],  # cosine distance. 類似度は 1.0 - distance
            "documents": [["text1", "text2"]],
            "metadatas": [[{"meta": "1"}, {"meta": "2"}]]
        }

        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            results = self.engine.search("query", top_k=2)
            assert len(results) == 2
            assert results[0].asset_id == "a1"
            assert results[0].score == 0.8  # 1.0 - 0.2
            assert results[1].asset_id == "a2"
            assert results[1].score == 0.1  # 1.0 - 0.9

    def test_get_index_stats(self):
        mock_collection.count.return_value = 10
        
        # CHROMA_DIR の glob モック
        mock_file1 = MagicMock()
        mock_file1.is_file.return_value = True
        mock_file1.stat.return_value.st_size = 2048 # 2KB

        mock_file2 = MagicMock()
        mock_file2.is_file.return_value = True
        mock_file2.stat.return_value.st_size = 1024 # 1KB

        with patch('services.vector_search.CHROMA_DIR') as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.rglob.return_value = [mock_file1, mock_file2]
            
            stats = self.engine.get_index_stats()
            assert stats["total_entries"] == 10
            assert stats["file_size_kb"] == 3.0 # (2048+1024)/1024

    def test_search_top_k_greater_than_count(self):
        # top_k がインデックス件数を超える場合の挙動検証
        mock_collection.count.return_value = 2
        mock_collection.query.return_value = {
            "ids": [["a1", "a2"]],
            "distances": [[0.1, 0.2]],
            "documents": [["text1", "text2"]],
            "metadatas": [[{"meta": "1"}, {"meta": "2"}]]
        }
        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            results = self.engine.search("query", top_k=5)
            mock_collection.query.assert_called_once_with(
                query_embeddings=[[0.1] * EMBEDDING_DIM],
                n_results=2
            )
            assert len(results) == 2

    def test_search_fallback_values(self):
        # ChromaDB 検索結果の各要素が None または空の場合のフォールバック検証
        mock_collection.count.return_value = 1
        mock_collection.query.return_value = {
            "ids": [["a1"]],
            "distances": None,
            "documents": None,
            "metadatas": None
        }
        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            results = self.engine.search("query", top_k=1)
            assert len(results) == 1
            assert results[0].asset_id == "a1"
            assert results[0].score == 1.0  # distanceフォールバック: 0.0 -> score: 1.0 - 0.0 = 1.0
            assert results[0].text_summary == ""  # textフォールバック: ""
            assert results[0].metadata == {}  # metadataフォールバック: {}

    def test_get_genai_client_singleton_cache(self):
        # 1回目：GOOGLE_API_KEY が設定され、正常にクライアントが生成される場合
        mock_client = MagicMock()
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "dummy_key"}),              patch('gemini_client_factory.get_gemini_client', return_value=mock_client) as mock_factory:
            client1 = self.engine._get_genai_client()
            assert client1 == mock_client
            mock_factory.assert_called_once()
            
            # 2回目：既に生成されているため、ファクトリを呼ばずにキャッシュを返すことを検証
            client2 = self.engine._get_genai_client()
            assert client2 == mock_client
            mock_factory.assert_called_once() # 呼び出し回数は1回のまま

    def test_rebuild_index_no_valid_ids(self):
        # 無効なデータのみを渡し、ids が空になって collection.add が呼ばれないケース
        mock_collection.count.side_effect = [3, 0] # 既存3件、再構築後は0件
        asset_texts = [
            {"invalid_field": "no_id_or_text"}
        ]
        res = self.engine.rebuild_index(asset_texts)
        assert res["success"] is True
        assert res["new_entries"] == 0
        mock_chroma_client.delete_collection.assert_called_once_with(COLLECTION_NAME)
        mock_collection.add.assert_not_called()

    def test_search_results_falsy_or_empty(self):
        # results が None, {}, {"ids": None}, {"ids": [[]]} などのケース
        mock_collection.count.return_value = 5
        
        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            # Case 1: results is None
            mock_collection.query.return_value = None
            res1 = self.engine.search("query")
            assert res1 == []

            # Case 2: results is empty dict
            mock_collection.query.return_value = {}
            res2 = self.engine.search("query")
            assert res2 == []

            # Case 3: results["ids"] is None
            mock_collection.query.return_value = {"ids": None}
            res3 = self.engine.search("query")
            assert res3 == []

            # Case 4: results["ids"] is empty
            mock_collection.query.return_value = {"ids": []}
            res4 = self.engine.search("query")
            assert res4 == []

            # Case 5: results["ids"][0] is empty
            mock_collection.query.return_value = {"ids": [[]]}
            res5 = self.engine.search("query")
            assert res5 == []

    def test_get_index_stats_dir_not_exists(self):
        # CHROMA_DIR が存在しないケース
        mock_collection.count.return_value = 0
        with patch('services.vector_search.CHROMA_DIR') as mock_dir:
            mock_dir.exists.return_value = False
            stats = self.engine.get_index_stats()
            assert stats["total_entries"] == 0
            assert stats["file_size_kb"] == 0.0

    def test_get_index_stats_with_directory_excluded(self):
        # CHROMA_DIR 内にファイルではない（ディレクトリ等の）オブジェクトが含まれるケース
        mock_collection.count.return_value = 1
        
        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_file.stat.return_value.st_size = 1024 # 1KB

        mock_sub_dir = MagicMock()
        mock_sub_dir.is_file.return_value = False # ファイルではない

        with patch('services.vector_search.CHROMA_DIR') as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.rglob.return_value = [mock_file, mock_sub_dir]
            
            stats = self.engine.get_index_stats()
            assert stats["total_entries"] == 1
            assert stats["file_size_kb"] == 1.0 # mock_sub_dir は除外されるため 1KB のみ

    def test_init_failure_fallback_to_dummy(self):
        # データベース接続失敗等で ChromaDB 初期化が例外を投げた場合、
        # 例外をキャッチして安全にダミーモードで動作することを検証
        with patch('chromadb.PersistentClient', side_effect=sqlite3.Error("database disk image is malformed")):
            engine = VectorSearchEngine()
            assert engine._chroma_client is None
            assert engine._collection is None

    def test_search_when_collection_is_none(self):
        # コレクションが None の場合、search がクラッシュせずに空リストを返すことを検証
        self.engine._collection = None
        res = self.engine.search("query")
        assert res == []

    def test_search_count_exception(self):
        # collection.count() が例外を投げた場合、search がクラッシュせずに空リストを返すことを検証
        mock_collection.count.side_effect = sqlite3.Error("Database locked")
        res = self.engine.search("query")
        assert res == []

    def test_search_query_exception(self):
        # collection.query() が例外を投げた場合、search がクラッシュせずに空リストを返すことを検証
        mock_collection.count.return_value = 5
        mock_collection.query.side_effect = RuntimeError("Chroma query failed")
        
        with patch.object(self.engine, '_get_embedding', return_value=[0.1] * EMBEDDING_DIM):
            res = self.engine.search("query")
            assert res == []

    def test_get_index_stats_when_collection_is_none(self):
        # コレクションが None の場合、get_index_stats がクラッシュせずに統計を返すことを検証
        self.engine._collection = None
        stats = self.engine.get_index_stats()
        assert stats["total_entries"] == 0
        assert stats["index_exists"] is False

    def test_get_index_stats_count_exception(self):
        # collection.count() が例外を投げた場合、get_index_stats がクラッシュせずに total_entries = 0 として動作することを検証
        mock_collection.count.side_effect = sqlite3.Error("Database disk image is malformed")
        stats = self.engine.get_index_stats()
        assert stats["total_entries"] == 0

    def test_get_index_stats_dir_rglob_exception(self):
        # ディレクトリ走査が OSError を投げた場合、get_index_stats がクラッシュせずに動作することを検証
        mock_collection.count.return_value = 1
        with patch('services.vector_search.CHROMA_DIR') as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.rglob.side_effect = OSError("Permission denied")
            
            stats = self.engine.get_index_stats()
            assert stats["total_entries"] == 1
            assert stats["file_size_kb"] == 0.0

    def test_get_index_stats_file_stat_exception(self):
        # ファイルの stat 取得で OSError が発生した場合、そのファイルをスキップして正常に動作することを検証
        mock_collection.count.return_value = 1
        
        mock_file1 = MagicMock()
        mock_file1.is_file.return_value = True
        mock_file1.stat.side_effect = OSError("Read error")

        mock_file2 = MagicMock()
        mock_file2.is_file.return_value = True
        mock_file2.stat.return_value.st_size = 2048 # 2KB

        with patch('services.vector_search.CHROMA_DIR') as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.rglob.return_value = [mock_file1, mock_file2]
            
            stats = self.engine.get_index_stats()
            assert stats["total_entries"] == 1
            assert stats["file_size_kb"] == 2.0  # mock_file1 はスキップされ、mock_file2 は加算される

    def test_get_genai_client_attribute_error(self):
        # get_gemini_client が AttributeError を投げた場合も None を返すことを検証
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "dummy_key"}), \
             patch('gemini_client_factory.get_gemini_client', side_effect=AttributeError("invalid attribute")):
            client = self.engine._get_genai_client()
            assert client is None

    def test_get_embedding_api_error_fallback(self):
        # embed_content が APIError を投げた場合にダミーにフォールバックすること
        from google.genai.errors import APIError
        err = APIError(code=400, response_json={"message": "API Error"})

        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = err

        with patch.object(self.engine, '_get_genai_client', return_value=mock_client):
            vec = self.engine._get_embedding("hello")
            assert len(vec) == EMBEDDING_DIM
            norm = sum(v * v for v in vec)
            assert abs(norm - 1.0) < 1e-5

    def test_get_embedding_index_error_fallback(self):
        # embed_content は成功するが result.embeddings[0] が IndexError を起こす場合
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.embeddings = []
        mock_client.models.embed_content.return_value = mock_result

        with patch.object(self.engine, '_get_genai_client', return_value=mock_client):
            vec = self.engine._get_embedding("hello")
            assert len(vec) == EMBEDDING_DIM
            norm = sum(v * v for v in vec)
            assert abs(norm - 1.0) < 1e-5

