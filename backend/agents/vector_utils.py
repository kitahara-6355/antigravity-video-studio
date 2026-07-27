import math
import logging
from typing import List
import httpx
from google.genai.errors import APIError

logger = logging.getLogger(__name__)

def _is_valid_numeric_list(v: List[float]) -> bool:
    """ベクトルが有効な数値のリスト（NaN, Inf を含まない）であるか検証する"""
    try:
        if not isinstance(v, list) or not v:
            return False
        for x in v:
            if isinstance(x, bool) or not isinstance(x, (int, float)) or math.isnan(x) or math.isinf(x):
                return False
        return True
    except (TypeError, ValueError, AttributeError, OverflowError) as e:
        logger.warning(f"Invalid elements or types in vector: {e}")
        return False

def get_embedding(client, text: str, model: str = "text-embedding-004") -> List[float]:
    """Gemini Clientを使用して文字列の埋め込みベクトルを取得する"""
    if client is None:
        logger.error("Gemini client is None.")
        return []
    if not text:
        return []
    try:
        response = client.models.embed_content(
            model=model,
            contents=text
        )
        if response and response.embedding and response.embedding.values:
            return response.embedding.values
        else:
            logger.error(f"Invalid or empty embedding response structure: response={response}")
    except APIError as e:
        logger.error(f"Failed to get embedding from Gemini API: {e}")
    except (AttributeError, TypeError, ValueError, KeyError, RuntimeError, IndexError, httpx.HTTPError) as e:
        logger.error(f"Invalid client, parameters, or network error for embedding: {e}")
    return []

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """2つのベクトルのコサイン類似度を計算する（外部ライブラリ依存なしで動作）"""
    if not isinstance(v1, list) or not isinstance(v2, list):
        logger.warning("cosine_similarity input v1 or v2 is not a list")
        return 0.0

    if not _is_valid_numeric_list(v1) or not _is_valid_numeric_list(v2):
        return 0.0

    if len(v1) != len(v2):
        return 0.0
        
    try:
        max_v1 = max(abs(x) for x in v1)
        max_v2 = max(abs(x) for x in v2)
        if max_v1 == 0.0 or max_v2 == 0.0:
            return 0.0
            
        v1_scaled = [x / max_v1 for x in v1]
        v2_scaled = [x / max_v2 for x in v2]
        
        dot_product = sum(x * y for x, y in zip(v1_scaled, v2_scaled))
        norm_v1 = math.sqrt(sum(x * x for x in v1_scaled))
        norm_v2 = math.sqrt(sum(x * x for x in v2_scaled))
        
        if norm_v1 == 0.0 or norm_v2 == 0.0:
            return 0.0
            
        prod = norm_v1 * norm_v2
        if prod == 0.0:
            # Prevent underflow resulting in ZeroDivisionError
            return 0.0
            
        val = dot_product / prod
        return max(-1.0, min(1.0, val))
    except (TypeError, ValueError, ArithmeticError, ZeroDivisionError, OverflowError) as e:
        logger.error(f"Error during cosine similarity calculation: {e}")
    return 0.0
