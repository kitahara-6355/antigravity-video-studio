"""
Vector Search Engine v3 — ChromaDB Backend
[Phase 5.2 & 5.3: Vector Index Builder + Natural Language Query]

v2 → v3 変更点:
- JSON全件走査 → ChromaDB ANN 検索（O(N) → O(log N)）
- 自作コサイン類似度 → ChromaDB 内蔵距離関数
- SafeJsonStore永続化 → ChromaDB 組み込みストレージ
- 公開API（build_index, rebuild_index, search, get_index_stats）は完全互換

Embedding:
- Google text-embedding-004 を使用（GOOGLE_API_KEY が必要）
- APIキー未設定時は SHA-256 ベースの STUB ベクトルにフォールバック
"""
import math
import hashlib
import logging
import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

import chromadb
from chromadb.config import Settings

from safe_io import VAULT_OUTPUTS_DIR

logger = logging.getLogger(__name__)

# ChromaDB 永続化ディレクトリ
CHROMA_DIR = VAULT_OUTPUTS_DIR / "chroma_db"
COLLECTION_NAME = "asset_vectors"
EMBEDDING_DIM = 768


@dataclass
class SearchResult:
    """ベクトル検索結果"""
    asset_id: str
    score: float          # 類似度スコア（0.0〜1.0、高いほど類似）
    text_summary: str     # 検索対象となったテキスト
    metadata: Dict[str, Any]


class VectorSearchEngine:
    """
    [Phase 5: Semantic Archive Search — ChromaDB Backend]
    素材エントリのベクトルインデックスを構築・管理し、
    自然言語クエリによるセマンティック検索を提供するエンジン。

    v3: ChromaDB による高速 ANN 検索。公開 API は v2 と完全互換。
    """

    def __init__(self):
        self._client_genai = None
        self._built_at: Optional[str] = None

        # ChromaDB 永続クライアント
        self._chroma_client = None
        self._collection = None
        try:
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(
                path=str(CHROMA_DIR),
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self._chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}  # コサイン距離
            )

            count = self._collection.count()
            if count > 0:
                logger.info(f"🔍 [VectorSearch] ChromaDB インデックス読み込み完了: {count}件")
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
            logger.error(f"❌ [VectorSearch] ChromaDB の初期化に失敗しました。ダミーモードで動作します: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # genai.Client シングルトン
    # ------------------------------------------------------------------
    def _get_genai_client(self):
        """genai.Client をシングルトンとして返す（初回のみ生成）"""
        if self._client_genai is None:
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if api_key:
                try:
                    from google import genai
                    from gemini_client_factory import get_gemini_client
                    self._client_genai = get_gemini_client()
                except (ImportError, AttributeError, RuntimeError, ValueError) as e:
                    logger.warning(f"[VectorSearch] genai.Client の初期化に失敗: {e}", exc_info=True)
        return self._client_genai

    # ------------------------------------------------------------------
    # Embedding 生成
    # ------------------------------------------------------------------
    def _get_embedding(self, text: str) -> List[float]:
        """
        テキストを Embedding ベクトルに変換する。
        Google text-embedding-004 を使用。API キーがない場合は STUB ベクトルを返す。
        """
        client = self._get_genai_client()
        if client is None:
            logger.warning("[STUB] GOOGLE_API_KEY が未設定のため、ダミー Embedding を使用します。")
            return self._stub_embedding(text)

        from google.genai.errors import APIError
        try:
            result = client.models.embed_content(
                model="text-embedding-004",
                contents=text
            )
            return result.embeddings[0].values
        except (APIError, IndexError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.warning(
                f"[STUB] Embedding API 呼び出し失敗 ({type(e).__name__}): {e}。ダミー Embedding にフォールバック。",
                exc_info=True
            )
            return self._stub_embedding(text)

    def _stub_embedding(self, text: str) -> List[float]:
        """
        STUB モード用の擬似 Embedding ベクトル。
        SHA-256 ダイジェストを用いた語順考慮の決定論的ダミーベクトルを生成する。
        """
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big")
        vec = []
        for i in range(EMBEDDING_DIM):
            val = math.sin(seed * 0.000001 + i * 0.7853981633974483)
            vec.append(val)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    # ------------------------------------------------------------------
    # インデックス構築（5.2）
    # ------------------------------------------------------------------
    def _prepare_index_data(
        self,
        asset_texts: List[Dict[str, Any]],
        filter_ids: Optional[set] = None
    ) -> Tuple[List[str], List[List[float]], List[str], List[Dict[str, Any]]]:
        """
        アセットテキストのリストから ChromaDB 登録用のデータを構築します。
        重複やバリデーションを行い、Embeddingの取得およびメタデータの安全化を処理します。
        """
        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for item in asset_texts:
            asset_id = item.get("asset_id", "")
            text = item.get("text", "")
            metadata = item.get("metadata", {})

            if not asset_id or not text:
                continue
            if filter_ids and asset_id in filter_ids:
                continue

            embedding = self._get_embedding(text)
            ids.append(asset_id)
            embeddings.append(embedding)
            documents.append(text)
            # ChromaDB metadata は文字列/数値/ブールのみ対応
            safe_meta = {}
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    safe_meta[k] = v
                elif v is None:
                    safe_meta[k] = ""
                else:
                    safe_meta[k] = str(v)
            # ChromaDB は空のメタデータ辞書を許容しないため、デフォルトキーを設定
            if not safe_meta:
                safe_meta = {"is_empty_meta": "true"}
            new_metadata = safe_meta
            metadatas.append(new_metadata)

        return ids, embeddings, documents, metadatas

    def build_index(self, asset_texts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        [5.2 Vector Index Builder] 差分更新モード
        既存エントリを保持しながら、新規アセットのみを追加する。

        Args:
            asset_texts: [{"asset_id": str, "text": str, "metadata": dict}, ...]

        Returns:
            インデックス構築結果サマリー
        """
        if self._collection is None:
            logger.warning("[VectorSearch] ChromaDB collection is not initialized.")
            return {"success": False, "message": "ベクトルデータベースが初期化されていないため、インデックスを構築できません。"}

        if not asset_texts:
            return {"success": False, "message": "インデックス化する素材がありません。"}

        # 既存 ID の取得
        existing_ids = set()
        try:
            if self._collection.count() > 0:
                all_data = self._collection.get()
                existing_ids = set(all_data["ids"])
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
            logger.error(f"[VectorSearch] 既存ID取得中にエラーが発生しました: {e}", exc_info=True)
            return {"success": False, "message": f"既存データ取得エラー: {e}"}

        new_ids, new_embeddings, new_documents, new_metadatas = self._prepare_index_data(
            asset_texts, filter_ids=existing_ids
        )

        if new_ids:
            try:
                self._collection.add(
                    ids=new_ids,
                    embeddings=new_embeddings,
                    documents=new_documents,
                    metadatas=new_metadatas
                )
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
                logger.error(f"[VectorSearch] インデックス追加中にエラーが発生しました: {e}", exc_info=True)
                return {"success": False, "message": f"インデックス追加エラー: {e}"}

        now = datetime.now().isoformat()
        self._built_at = now
        try:
            total = self._collection.count()
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            total = len(existing_ids) + len(new_ids)

        logger.info(f"📦 [VectorSearch] インデックス構築完了（差分）: 新規{len(new_ids)}件 / 合計{total}件")
        return {
            "success": True,
            "mode": "incremental",
            "new_entries": len(new_ids),
            "total_entries": total,
            "built_at": now,
            "message": f"{len(new_ids)}件の素材をインデックスに追加しました。"
        }

    def rebuild_index(self, asset_texts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        [5.2 Vector Index Builder] 全面再構築モード
        既存インデックスを完全に破棄し、全アセットを再ベクトル化する。

        Args:
            asset_texts: [{"asset_id": str, "text": str, "metadata": dict}, ...]

        Returns:
            インデックス再構築結果サマリー
        """
        if self._chroma_client is None or self._collection is None:
            logger.warning("[VectorSearch] ChromaDB client/collection is not initialized.")
            return {"success": False, "message": "ベクトルデータベースが初期化されていないため、インデックスを再構築できません。"}

        if not asset_texts:
            return {"success": False, "message": "インデックス化する素材がありません。"}

        try:
            old_count = self._collection.count()
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            old_count = 0
        logger.info(f"🔄 [VectorSearch] 全面再構築開始: 既存{old_count}件を破棄し、{len(asset_texts)}件を再構築します。")

        try:
            # コレクションを削除して再作成
            self._chroma_client.delete_collection(COLLECTION_NAME)
            self._collection = self._chroma_client.create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
            logger.error(f"[VectorSearch] コレクションの再作成中にエラーが発生しました: {e}", exc_info=True)
            return {"success": False, "message": f"コレクション再作成エラー: {e}"}

        ids, embeddings, documents, metadatas = self._prepare_index_data(asset_texts)

        if ids:
            try:
                self._collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas
                )
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
                logger.error(f"[VectorSearch] インデックス登録中にエラーが発生しました: {e}", exc_info=True)
                return {"success": False, "message": f"インデックス登録エラー: {e}"}

        now = datetime.now().isoformat()
        self._built_at = now
        try:
            total = self._collection.count()
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            total = len(ids)

        logger.info(f"📦 [VectorSearch] インデックス全面再構築完了: {total}件")
        return {
            "success": True,
            "mode": "rebuild",
            "new_entries": total,
            "total_entries": total,
            "built_at": now,
            "message": f"全{total}件 of インデックスを再構築しました。"
        }

    # ------------------------------------------------------------------
    # 自然言語検索（5.3）
    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """
        [5.3 Natural Language Query]
        自然言語クエリで素材を検索し、類似度の高い順に返す。

        Args:
            query: 検索クエリ（例: "暖色系のBGM", "プロフェッショナルな人物写真"）
            top_k: 返す件数

        Returns:
            SearchResult のリスト（スコア降順）
        """
        if top_k <= 0:
            return []

        if self._collection is None:
            logger.warning("[VectorSearch] コレクションが初期化されていません。")
            return []

        try:
            count = self._collection.count()
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
            logger.error(f"[VectorSearch] インデックス件数取得中にエラーが発生しました: {e}", exc_info=True)
            return []

        if count == 0:
            logger.warning("[VectorSearch] インデックスが空です。まず /assets/build-index を実行してください。")
            return []

        query_embedding = self._get_embedding(query)

        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, count)
            )
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
            logger.error(f"[VectorSearch] 検索クエリ実行中にエラーが発生しました: {e}", exc_info=True)
            return []

        search_results = []
        if results and results["ids"] and results["ids"][0]:
            for i, asset_id in enumerate(results["ids"][0]):
                # ChromaDB のコサイン距離 → 類似度スコアに変換
                distance = results["distances"][0][i] if results["distances"] else 0.0
                score = max(0.0, min(1.0, round(1.0 - distance, 4)))  # 0.0〜1.0にクリップ

                text = results["documents"][0][i] if results["documents"] else ""
                meta = results["metadatas"][0][i] if results["metadatas"] else {}

                search_results.append(SearchResult(
                    asset_id=asset_id,
                    score=score,
                    text_summary=text,
                    metadata=meta
                ))

        logger.info(f"🔎 [VectorSearch] 検索完了: クエリ='{query[:30]}' / 上位{len(search_results)}件を返却")
        return search_results

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------
    def get_index_stats(self) -> Dict[str, Any]:
        """インデックスの統計情報を返す"""
        total = 0
        if self._collection is not None:
            try:
                total = self._collection.count()
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as e:
                logger.error(f"[VectorSearch] 統計用のインデックス件数取得中にエラーが発生しました: {e}", exc_info=True)

        # ChromaDB ディレクトリサイズ
        dir_size = 0
        try:
            if CHROMA_DIR.exists():
                for f in CHROMA_DIR.rglob("*"):
                    try:
                        if f.is_file():
                            dir_size += f.stat().st_size
                    except OSError as e:
                        logger.warning(f"[VectorSearch] ファイル統計取得失敗 (スキップ): {f} - {e}")
        except OSError as e:
            logger.warning(f"[VectorSearch] ディレクトリ走査に失敗しました: {e}")

        return {
            "total_entries": total,
            "backend": "ChromaDB",
            "index_dir": str(CHROMA_DIR),
            "index_exists": total > 0,
            "built_at": self._built_at,
            "embedding_dim": EMBEDDING_DIM,
            "file_size_kb": round(dir_size / 1024, 1)
        }


# Singleton
vector_search_engine = VectorSearchEngine()

