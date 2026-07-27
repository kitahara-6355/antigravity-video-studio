"""
Embedding Service — Embedding 生成の一元管理

CR-02 対応: プロジェクト全体で使用される Embedding 生成を
このモジュールに集約し、モデル名・フォールバック・キャッシングを
一箇所で管理する。

使い方:
    from services.embedding_service import get_embedding

    vector = get_embedding("検索テキスト")
    # → List[float] (768次元)

設計方針:
- GeminiClientFactory 経由でクライアントを取得
- API キー未設定時は STUB ベクトルを返す（開発用）
- モデル名を一箇所で管理（将来の変更に強い）
- スレッドセーフ
"""

import hashlib
import logging
from typing import List, Optional, Union

from google.genai.errors import APIError

logger = logging.getLogger(__name__)

# ========================================
# 定数
# ========================================
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIMENSION = 768  # text-embedding-004 の出力次元


def get_embedding(text: str) -> List[float]:
    """
    テキストを Embedding ベクトルに変換する。

    Google text-embedding-004 を使用。
    API キーが未設定の場合は決定論的な STUB ベクトルを返す。

    Args:
        text: Embedding 対象 of テキスト

    Returns:
        List[float]: EMBEDDING_DIMENSION 次元のベクトル
    """
    return _embed_contents_or_fallback(text, is_batch=False)


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    複数テキストのバッチ Embedding 生成。

    100件以上のバッチは、API制限やタイムアウト防止のため100件ずつのチャンクに分割して処理する。
    一部のチャンクでエラーが発生した場合、そのチャンクのみスタブにフォールバックしてマージする。

    Args:
        texts: テキストのリスト

    Returns:
        List[List[float]]: 各テキストに対応するベクトルのリスト
    """
    if not texts:
        return []
    if not isinstance(texts, list):
        if isinstance(texts, str):
            return _embed_contents_or_fallback(texts, is_batch=True)
        try:
            texts = list(texts)
        except TypeError:
            return _embed_contents_or_fallback(texts, is_batch=True)
    
    CHUNK_SIZE = 100
    results = []
    for i in range(0, len(texts), CHUNK_SIZE):
        chunk = texts[i:i + CHUNK_SIZE]
        chunk_results = _embed_contents_or_fallback(chunk, is_batch=True)
        if isinstance(chunk_results, list) and len(chunk_results) == len(chunk):
            results.extend(chunk_results)
        else:
            logger.warning(
                f"[STUB] チャンク処理の結果が不正です（型: {type(chunk_results)}）。"
                f"個別のスタブにフォールバックします。"
            )
            results.extend([_stub_embedding(t) for t in chunk])
    return results


def _embed_contents_or_fallback(contents: Union[str, List[str]], is_batch: bool) -> Union[List[float], List[List[float]]]:
    """
    Gemini API を用いてテキストまたはテキストリスト of Embedding を生成する。
    失敗時や API キー未設定時は決定論的なダミー（STUB）ベクトルを返す。
    """
    # 入力値の検証
    try:
        if contents is None:
            raise TypeError("contents cannot be None")
        
        if is_batch:
            if not isinstance(contents, list):
                raise TypeError("contents must be a list of strings for batch processing")
            if not all(isinstance(t, str) for t in contents):
                raise TypeError("all elements in contents batch must be strings")
        else:
            if not isinstance(contents, str):
                raise TypeError("contents must be a string")
    except TypeError as e:
        if not is_batch:
            logger.warning(f"[STUB] 不正な入力型が検出されました ({e})。ダミー Embedding にフォールバックします。")
            return _stub_embedding(contents)
        else:
            logger.warning(f"[STUB] バッチ入力内に不正な入力型が検出されました ({e})。ダミー Embedding にフォールバックします。")
            if not isinstance(contents, list):
                return [_stub_embedding(str(contents))]
            return [_stub_embedding(t) for t in contents]

    try:
        from gemini_client_factory import get_gemini_client
        client = get_gemini_client()
    except (NameError, TypeError, ValueError, UnboundLocalError, SyntaxError, KeyError, IndexError, ImportError, ModuleNotFoundError, NotImplementedError, AttributeError, AssertionError, ArithmeticError, LookupError) as e:
        logger.error(f"プログラムエラーが検出されました。スタブへのフォールバックは行いません ({type(e).__name__}: {e})。", exc_info=True)
        raise e
    except Exception as e:
        if not is_batch:
            logger.error(f"[STUB] クライアント取得中に想定外の深刻なエラーが発生しました ({type(e).__name__}: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
            return _stub_embedding(contents)
        else:
            logger.error(f"[STUB] クライアント取得中に想定外の深刻なエラーが発生しました ({type(e).__name__}: {e})。バッチ処理でダミー Embedding にフォールバックします。", exc_info=True)
            return [_stub_embedding(t) for t in contents]

    if client is None:
        if not is_batch:
            logger.warning("[STUB] GOOGLE_API_KEY が未設定のため、ダミー Embedding を使用します。")
            return _stub_embedding(contents)
        else:
            logger.warning("[STUB] GOOGLE_API_KEY が未設定のため、バッチ処理でダミー Embedding を使用します。")
            return [_stub_embedding(t) for t in contents]

    # API 呼び出しフェーズ
    try:
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=contents
        )
    except Exception as e:
        # APIError がモック汚染などで有効な例外クラスでない場合を考慮
        is_api_error = False
        try:
            if APIError is not None and isinstance(APIError, type) and issubclass(APIError, BaseException):
                if isinstance(e, APIError):
                    is_api_error = True
            elif type(e).__name__ == "APIError":
                is_api_error = True
        except Exception:
            if type(e).__name__ == "APIError":
                is_api_error = True

        if is_api_error:
            if not is_batch:
                logger.warning(f"[STUB] Embedding API 呼び出し失敗 (APIError: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
                return _stub_embedding(contents)
            else:
                logger.warning(f"[STUB] バッチ Embedding 失敗 (APIError: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
                return [_stub_embedding(t) for t in contents]

        # 一時的なインフラエラー
        if isinstance(e, (ConnectionError, TimeoutError)):
            if not is_batch:
                logger.warning(f"[STUB] 一時的なインフラエラーが発生しました ({type(e).__name__}: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
                return _stub_embedding(contents)
            else:
                logger.warning(f"[STUB] バッチ処理中に一時的なインフラエラーが発生しました ({type(e).__name__}: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
                return [_stub_embedding(t) for t in contents]
        
        # プログラムエラー
        if isinstance(e, (NameError, TypeError, ValueError, UnboundLocalError, SyntaxError, KeyError, IndexError, ImportError, ModuleNotFoundError, NotImplementedError, AttributeError, AssertionError, ArithmeticError, LookupError)):
            logger.error(f"プログラムエラーが検出されました。スタブへのフォールバックは行いません ({type(e).__name__}: {e})。", exc_info=True)
            raise e

        # 想定外の深刻なエラー
        if not is_batch:
            logger.error(f"[STUB] API呼び出し中に想定外の深刻なエラーが発生しました ({type(e).__name__}: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
            return _stub_embedding(contents)
        else:
            logger.error(f"[STUB] API呼び出し中に想定外の深刻なエラーが発生しました ({type(e).__name__}: {e})。バッチ処理でダミー Embedding にフォールバックします。", exc_info=True)
            return [_stub_embedding(t) for t in contents]

    # レスポンス解析フェーズ
    try:
        if not is_batch:
            if result.embeddings is None:
                raise ValueError("embeddings attribute is None")
            if not result.embeddings:
                raise ValueError("embeddings list is empty")
            emb = result.embeddings[0]
            if emb is None:
                raise ValueError("embedding element is None")
            if not hasattr(emb, "values") or emb.values is None:
                raise ValueError("embedding values attribute is missing or None")
            if not isinstance(emb.values, list) or len(emb.values) != EMBEDDING_DIMENSION:
                raise ValueError(f"embedding dimension mismatch: expected {EMBEDDING_DIMENSION}, got {len(emb.values) if isinstance(emb.values, list) else 'non-list'}")
            return emb.values
        else:
            if result.embeddings is None:
                raise ValueError("embeddings attribute is None")
            
            if len(result.embeddings) != len(contents):
                raise ValueError(f"embeddings count mismatch: expected {len(contents)}, got {len(result.embeddings)}")
            vecs = []
            for emb in result.embeddings:
                if emb is None:
                    raise ValueError("embedding element is None")
                if not hasattr(emb, "values") or emb.values is None:
                    raise ValueError("embedding values attribute is missing or None")
                if not isinstance(emb.values, list) or len(emb.values) != EMBEDDING_DIMENSION:
                    raise ValueError(f"embedding dimension mismatch: expected {EMBEDDING_DIMENSION}, got {len(emb.values) if isinstance(emb.values, list) else 'non-list'}")
                vecs.append(emb.values)
            return vecs
    except (ValueError, AttributeError, IndexError, KeyError) as e:
        # 解析時のデータ構造エラーは外部要因としてスタブフォールバック
        if not is_batch:
            logger.warning(f"[STUB] レスポンス解析失敗 (不正なレスポンス構造: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
            return _stub_embedding(contents)
        else:
            logger.warning(f"[STUB] バッチレスポンス解析失敗 (不正なレスポンス構造: {e})。ダミー Embedding にフォールバックします。", exc_info=True)
            return [_stub_embedding(t) for t in contents]
    except (NameError, TypeError, UnboundLocalError, SyntaxError, ImportError, ModuleNotFoundError, NotImplementedError, AssertionError, ArithmeticError, LookupError) as e:
        logger.error(f"プログラムエラーが検出されました。スタブへのフォールバックは行いません ({type(e).__name__}: {e})。", exc_info=True)
        raise e


def _stub_embedding(text: str) -> List[float]:
    """
    STUB モード用の擬似 Embedding ベクトル。
    SHA-256 ダイジェストを用いた決定論的ダミーベクトルを生成する。

    同一テキストに対しては常に同じベクトルを返す。
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    vec = []
    for i in range(EMBEDDING_DIMENSION):
        # 決定論的な擬似乱数生成
        seed = (seed * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        val = ((seed >> 33) / (1 << 31)) - 1.0  # -1.0 ～ 1.0
        vec.append(val)
    return vec
