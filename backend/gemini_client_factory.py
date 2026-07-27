"""
Gemini Client Factory — genai.Client の集中管理

AR-01 対応: 40+ 箇所で分散生成されている genai.Client を
一元管理するファクトリ。新規コードはこのファクトリ経由で
クライアントを取得すること。

Phase E: Strangler Fig パターンで GovernedModelsProxy を自動適用。
get_gemini_client() は自动的にフォールバック付きプロキシを返す。
_get_raw_client() は model_governance 内部専用の生クライアント。

設計方針:
- シングルトンクライアント（API キーごとに1つだけ生成）
- API キー変更時の自動再生成
- GOOGLE_API_KEY 未設定時は None を返す（呼び出し元で STUB 判定）
- スレッドセーフ
- get_gemini_client() → GovernedClient自動ラップ（deprecated差替+フォールバック）

使い方:
    from gemini_client_factory import get_gemini_client

    client = get_gemini_client()
    if client is None:
        # STUB モードで動作
        ...
    else:
        response = client.models.generate_content(...)
"""
import os
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached_raw_client = None
_current_api_key: Optional[str] = None

# GovernedClient キャッシュ（raw client に1:1対応）
_cached_governed_client = None


class GovernedAioProxy:
    def __init__(self, raw_aio):
        from model_governance import GovernedAsyncModelsProxy
        self._raw = raw_aio
        self.models = GovernedAsyncModelsProxy(raw_aio.models, "gemini_client_factory")

    def __getattr__(self, name):
        return getattr(self._raw, name)


class GovernedClient:
    """自動フォールバック付き genai.Client プロキシ"""
    def __init__(self, raw_client):
        from model_governance import GovernedModelsProxy
        self._raw = raw_client
        self.models = GovernedModelsProxy(raw_client.models, "gemini_client_factory")
        if hasattr(raw_client, "aio"):
            self.aio = GovernedAioProxy(raw_client.aio)

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _get_api_key() -> Optional[str]:
    """GOOGLE_API_KEY を環境変数から取得する。"""
    return os.getenv("GOOGLE_API_KEY")


def _create_raw_client(api_key: str):
    """genai.Client の生インスタンスを生成する。"""
    from google import genai
    return genai.Client(api_key=api_key)


def _is_raw_client_valid(cached_raw_client, current_api_key, target_api_key) -> bool:
    """キャッシュされた raw_client が有効であり、現在の API キーと一致するか検証する"""
    return cached_raw_client is not None and current_api_key == target_api_key


def _get_raw_client():
    """
    genai.Client の生インスタンスを返す（内部用）。

    model_governance.call() や get_governed_client() はこれを使用。
    外部コードは get_gemini_client() を使用すること。

    Returns:
        genai.Client or None
    """
    global _cached_raw_client, _current_api_key

    api_key = _get_api_key()
    if not api_key:
        return None

    # キーが変わっていなければ既存クライアントを返す（ロック不要）
    if _is_raw_client_valid(_cached_raw_client, _current_api_key, api_key):
        return _cached_raw_client

    with _lock:
        # ダブルチェックロック
        if _is_raw_client_valid(_cached_raw_client, _current_api_key, api_key):
            return _cached_raw_client

        try:
            client = _create_raw_client(api_key)
            _cached_raw_client = client
            _current_api_key = api_key
            logger.info("✅ [GeminiClientFactory] クライアントを初期化しました")
            return _cached_raw_client
        except (ImportError, ValueError) as e:
            logger.exception("❌ [GeminiClientFactory] クライアント初期化失敗: %s", e)
            _cached_raw_client = None
            _current_api_key = None
            return None


def _is_governed_client_valid(governed_client, raw_client) -> bool:
    """キャッシュされた GovernedClient が有効であり、指定された raw_client に紐付いているか検証する"""
    if governed_client is None:
        return False
    return getattr(governed_client, '_raw', None) is raw_client


def _create_governed_client_safely(raw_client):
    """GovernedClient を安全に生成し、失敗した場合は警告を出力して生クライアントを返す"""
    try:
        return GovernedClient(raw_client)
    except ImportError as e:
        # model_governance 未導入時は生クライアントを返す
        logger.warning("⚠️ [GeminiClientFactory] model_governance 未導入。生クライアントでフォールバックします: %s", e)
        return raw_client
    except Exception as e:
        logger.warning("⚠️ [GeminiClientFactory] model_governance 適用失敗。生クライアントでフォールバックします: %s", e)
        try:
            from agents.memory.technical_debt import technical_debt_store
            technical_debt_store.register_debt(
                category="ACCEPTED_SAFETY",
                file_path="backend/gemini_client_factory.py",
                line_number=136,
                pattern="except Exception as e: model_governance 適用時のフォールバック",
                cause_pattern="DP-02",
                fix_pattern="model_governance内の例外を具体的にキャッチするか、適用前にチェックする",
                registered_by="Phase 33",
                notes=f"model_governance適用時の最終フォールバック: {str(e)[:100]}"
            )
        except (ImportError, AttributeError, KeyError) as e_td:
            logger.warning("技術負債の自動登録に失敗しました: %s", e_td)
        return raw_client


def get_gemini_client():
    """
    GovernedModelsProxy 付き Gemini Client を返す。

    Phase E (Strangler Fig): 全26箇所の呼び出し元を変更せずに
    自動フォールバック + deprecated差替 + 監査ログを適用。

    - deprecated モデル → 自動差替
    - 429/503/404 → フォールバックチェーンで自動降格
    - 全操作を監査ログに記録

    Returns:
        GovernedClient or None
    """
    global _cached_governed_client

    raw_client = _get_raw_client()
    if raw_client is None:
        return None

    # raw client が変わっていなければキャッシュを返す
    if _is_governed_client_valid(_cached_governed_client, raw_client):
        return _cached_governed_client

    with _lock:
        # ダブルチェックロック
        if _is_governed_client_valid(_cached_governed_client, raw_client):
            return _cached_governed_client

        client_or_raw = _create_governed_client_safely(raw_client)
        if isinstance(client_or_raw, GovernedClient):
            _cached_governed_client = client_or_raw
        return client_or_raw


def reset_client():
    """
    テスト用: クライアントをリセットする。
    """
    global _cached_raw_client, _current_api_key, _cached_governed_client
    with _lock:
        _cached_raw_client = None
        _current_api_key = None
        _cached_governed_client = None
