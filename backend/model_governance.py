"""
Model Governance — ハーネス統合型モデルガバナンス

3層の防御でモデル異常を完全自動修復:

  Layer 1: PreToolUse Hook — deprecated モデル名の事前差替
  Layer 2: Fallback Chain  — 429/503/404 エラー時の自動降格
  Layer 3: Audit Trail     — 全差替・フォールバックを監査記録

対応するモデル異常:
  - 枠枯渇 (429 RESOURCE_EXHAUSTED) → フォールバックチェーンで次のモデルへ
  - 旧モデル利用不可 (404/quota=0)  → deprecated差替 + フォールバック
  - サーバー混雑 (503 UNAVAILABLE)   → リトライ → フォールバック
  - 新モデル未反映                    → model_config.json 再読込で動的対応

Fallback Chain (model_config.json から自動読込):
  gemini-3-flash-preview → gemini-2.5-flash → gemini-2.5-flash-lite → None(エラー)
"""

import json
import logging
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from google.genai.errors import APIError
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)

# ============================================================
# モデルガバナンスエンジン
# ============================================================

class ModelGovernanceEngine:
    """
    実行時モデルガバナンス + 自動フォールバック。

    全 Gemini API 呼び出しで:
      1. deprecated モデル → 自動差替
      2. APIエラー (429/503/404) → フォールバックチェーンで自動降格
      3. 全操作を監査ログに記録
    """

    _instance = None
    _lock = threading.Lock()

    # フォールバック対象のエラーコード
    FALLBACK_ERROR_CODES = {429, 503, 404}
    FALLBACK_ERROR_KEYWORDS = [
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "NOT_FOUND",
        "quota",
        "limit: 0",
    ]

    # リトライ設定
    MAX_RETRY_PER_MODEL = 1
    RETRY_DELAY_SECONDS = 2

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._deprecation_map: Dict[str, str] = {}
        self._fallback_chain: Dict[str, Optional[str]] = {}
        self._task_mapping: Dict[str, str] = {}
        self._default_model: str = "gemini-2.5-flash"
        self._event_log: List[Dict] = []
        self._stats = {
            "deprecation_corrections": 0,
            "fallback_activations": 0,
            "total_api_errors": 0,
        }
        self._load_config()

    def _load_config(self):
        """model_config.json から deprecation + fallback chain + task_mapping を読込"""
        config_path = Path(__file__).parent / "model_config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # deprecated マップ
            deprecated = config.get("deprecated", {})
            for old_model, info in deprecated.items():
                replacement = info.get("replacement")
                if replacement:
                    self._deprecation_map[old_model] = replacement

            # フォールバックチェーン
            text_gen = config.get("text_generation", {})
            self._fallback_chain = text_gen.get("fallback_chain", {})

            # タスク→モデル マッピング
            self._task_mapping = config.get("task_mapping", {})
            self._default_model = text_gen.get(
                "default_model", "gemini-2.5-flash"
            )

            logger.info(
                f"🛡️ ModelGovernance: "
                f"{len(self._deprecation_map)} deprecation rules, "
                f"{len(self._fallback_chain)} fallback chain entries, "
                f"{len(self._task_mapping)} task mappings loaded"
            )
        except FileNotFoundError as e:
            logger.warning(f"ModelGovernance: config file not found: {e}")
        except json.JSONDecodeError as e:
            logger.warning(f"ModelGovernance: config JSON decode failed: {e}")
        except PermissionError as e:
            logger.warning(f"ModelGovernance: config permission error: {e}")

    # ============================================================
    # Layer 1: deprecated 差替
    # ============================================================

    def validate_and_correct(self, model: str, caller: str = "") -> str:
        """deprecated モデルを replacement に差替（チェーン対応）"""
        if model not in self._deprecation_map:
            return model

        # チェーンで deprecated を辿る（A→B→C の場合 C を返す）
        visited = {model}
        current = self._deprecation_map[model]
        while current in self._deprecation_map:
            if current in visited:
                break
            visited.add(current)
            current = self._deprecation_map[current]

        self._stats["deprecation_corrections"] += 1
        self._record_event("deprecation", model, current, caller)

        logger.warning(
            f"🛡️ ModelGovernance: '{model}' → '{current}' "
            f"(deprecated auto-corrected, caller={caller})"
        )
        return current

    # ============================================================
    # Layer 2: フォールバックチェーン
    # ============================================================

    def get_fallback(self, model: str) -> Optional[str]:
        """次のフォールバックモデルを返す。末端なら None。"""
        return self._fallback_chain.get(model)

    def is_fallback_error(self, error) -> bool:
        """このエラーがフォールバック対象か判定"""
        error_str = str(error)
        return any(kw in error_str for kw in self.FALLBACK_ERROR_KEYWORDS)

    def build_fallback_sequence(self, start_model: str) -> List[str]:
        """フォールバックチェーン全体を配列で返す"""
        sequence = [start_model]
        current = start_model
        visited = {current}
        while True:
            next_model = self._fallback_chain.get(current)
            if next_model is None or next_model in visited:
                break
            sequence.append(next_model)
            visited.add(next_model)
            current = next_model
        return sequence

    # ============================================================
    # Layer 3: 監査ログ
    # ============================================================

    def _record_event(
        self, event_type: str, original: str,
        resolved: str, caller: str, error: str = "",
    ):
        self._event_log.append({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "original": original,
            "resolved": resolved,
            "caller": caller,
            "error": error[:200] if error else "",
        })
        if len(self._event_log) > 200:
            self._event_log = self._event_log[-100:]

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "deprecation_map": dict(self._deprecation_map),
            "fallback_chain": dict(self._fallback_chain),
            "task_mapping": dict(self._task_mapping),
            "recent_events": self._event_log[-10:],
        }

    def reload(self):
        """model_config.json を再読込"""
        self._deprecation_map.clear()
        self._fallback_chain.clear()
        self._task_mapping = {}
        self._load_config()

    # ============================================================
    # Layer 4: 統一 API ゲートウェイ
    # ============================================================

    def _resolve_model(self, task: str, model: Optional[str] = None) -> str:
        """タスク名からモデルを解決（枠チェック付き）。

        解決フロー:
          1. 明示的 model 指定 or task_mapping or default_model
          2. deprecated 差替
          3. 枠チェック → 枯渇なら fallback_chain で自動降格（プロアクティブ）

        これにより「Premium → Standard → Batch」の順で消費し、
        枯渇時に自動降格する設計意図を実現する。
        GovernedModelsProxy（ランタイム429対応）との二重防御。
        """
        if model:
            resolved = model
        else:
            resolved = self._task_mapping.get(task, self._default_model)

        # deprecated 差替
        resolved = self.validate_and_correct(resolved, f"resolve:{task}")

        # 枠チェック → 枯渇なら自動降格（プロアクティブ）
        try:
            from usage_tracker.tracker import usage_tracker as _ut
            original = resolved
            visited = {resolved}  # 無限ループ防止
            while resolved and not _ut.can_make_request(resolved):
                fallback = self._fallback_chain.get(resolved)
                if fallback is None or fallback in visited:
                    # チェーン末端 → 最後のモデルを返す
                    # GovernedModelsProxy が最終安全弁として機能
                    break
                visited.add(fallback)
                self._stats["fallback_activations"] += 1
                self._record_event(
                    "quota_precheck_fallback", resolved, fallback,
                    f"resolve:{task}",
                    f"usage={_ut.get_usage_ratio(resolved):.1%}",
                )
                logger.warning(
                    f"🛡️ ModelGovernance: '{resolved}' 枠枯渇 → "
                    f"'{fallback}' に降格 (task={task})"
                )
                resolved = fallback
        except ImportError:
            pass  # usage_tracker 未導入時は枠チェックスキップ
        except (AttributeError, TypeError, ImportError, RuntimeError) as e:
            logger.debug(f"Quota precheck skipped: {e}")

        return resolved

    async def call(
        self,
        *,
        task: str,
        prompt: str,
        caller: str = "",
        model: str = None,
        config: dict = None,
    ) -> str:
        """統一 Gemini API ゲートウェイ。

        全 AI Worker はこのメソッド経由で Gemini API を呼び出す。
        タスク名からモデルを自動選択し、フォールバック・RPD追跡・
        監査ログを透過的に適用する。

        Args:
            task:   タスク名 (model_config.json の task_mapping キー)
            prompt: プロンプト文字列
            caller: 呼び出し元の識別子（監査ログ用）
            model:  明示的モデル指定（taskより優先）
            config: generate_content への追加パラメータ

        Returns:
            生成テキスト

        Raises:
            RuntimeError: 全フォールバック枯渇時
            ValueError:   API キー未設定時
        """
        import asyncio
        from gemini_client_factory import _get_raw_client

        client = _get_raw_client()
        if client is None:
            raise ValueError(
                "GOOGLE_API_KEY が未設定です。"
                "Gemini API を使用するには .env に設定してください。"
            )

        # 1. モデル解決 (task → model)
        resolved_model = self._resolve_model(task, model)
        caller_id = caller or task

        # 2. フォールバックチェーン構築
        chain = self.build_fallback_sequence(resolved_model)

        # 3. チェーンを順に試行
        last_error = None
        for i, try_model in enumerate(chain):
            try:
                # 非同期 API 呼び出し
                gen_kwargs = {"model": try_model, "contents": prompt}
                if config:
                    gen_kwargs.update(config)

                # genai.Client は aio.models.generate_content を持つ
                if hasattr(client, "aio") and hasattr(client.aio, "models"):
                    response = await client.aio.models.generate_content(
                        **gen_kwargs
                    )
                else:
                    # 同期クライアントの場合はスレッドプールで実行
                    response = await asyncio.to_thread(
                        client.models.generate_content, **gen_kwargs
                    )

                # RPD 自動カウント
                self._track_usage(try_model, caller_id)

                # フォールバック成功ログ
                if i > 0:
                    self._stats["fallback_activations"] += 1
                    self._record_event(
                        "fallback_success", resolved_model, try_model,
                        caller_id,
                    )
                    logger.info(
                        f"🛡️ Gateway fallback success: "
                        f"'{resolved_model}' → '{try_model}' "
                        f"(caller={caller_id})"
                    )

                # 成功ログ
                self._record_event(
                    "api_call", try_model, try_model, caller_id,
                )

                return response.text

            except (APIError, GoogleAPICallError) as e:
                last_error = e
                self._stats["total_api_errors"] += 1

                if not self.is_fallback_error(e):
                    # フォールバック対象外 → そのまま raise
                    self._record_event(
                        "api_error", try_model, "",
                        caller_id, str(e),
                    )
                    raise

                next_model = chain[i + 1] if i + 1 < len(chain) else None
                if next_model:
                    self._record_event(
                        "fallback_attempt", try_model, next_model,
                        caller_id, str(e),
                    )
                    logger.warning(
                        f"🛡️ Gateway: '{try_model}' failed, "
                        f"falling back to '{next_model}' "
                        f"(caller={caller_id})"
                    )
                    await asyncio.sleep(self.RETRY_DELAY_SECONDS)
                else:
                    self._record_event(
                        "fallback_exhausted", resolved_model, try_model,
                        caller_id, str(e),
                    )
                    logger.error(
                        f"🛡️ Gateway: all models exhausted! "
                        f"chain={' → '.join(chain)}, "
                        f"caller={caller_id}"
                    )
                    raise RuntimeError(
                        f"全フォールバック枯渇: {' → '.join(chain)}"
                    ) from last_error

        raise last_error  # 到達しないはずだが安全のため

    def _track_usage(self, model: str, caller: str):
        """RPD 自動カウント（usage_tracker 統合）"""
        try:
            from usage_tracker.tracker import usage_tracker
            result = usage_tracker.track_request(model)

            if result.get("alert_level") in ("warning", "block", "critical"):
                self._record_event(
                    "quota_alert", model, model, caller,
                    f"alert_level={result['alert_level']}, "
                    f"usage={result.get('usage_ratio', 0):.1%}",
                )
        except (AttributeError, TypeError, ImportError, OSError) as e:
            logger.debug(f"Usage tracking skipped: {e}")


# シングルトン
model_governance = ModelGovernanceEngine()


# ============================================================
# Governed Client — 自動フォールバック付きプロキシ
# ============================================================

class GovernedModelsProxy:
    """
    client.models のプロキシ。

    1. deprecated モデル → 自動差替
    2. API エラー (429/503/404) → フォールバックチェーンで自動降格
    3. 全操作を監査ログに記録
    """

    def __init__(self, real_models, caller: str = ""):
        self._real = real_models
        self._caller = caller

    def generate_content(self, *, model: str, **kwargs):
        """同期版: フォールバック付き generate_content"""
        # Layer 1: deprecated 差替
        model = model_governance.validate_and_correct(model, self._caller)

        # Layer 2: フォールバックチェーンを順に試行
        chain = model_governance.build_fallback_sequence(model)

        last_error = None
        for i, try_model in enumerate(chain):
            try:
                result = self._real.generate_content(model=try_model, **kwargs)

                if i > 0:
                    # フォールバックで成功した場合
                    model_governance._stats["fallback_activations"] += 1
                    model_governance._record_event(
                        "fallback_success", model, try_model,
                        self._caller,
                    )
                    logger.info(
                        f"🛡️ ModelGovernance: fallback success "
                        f"'{model}' → '{try_model}' (caller={self._caller})"
                    )

                return result

            except (APIError, GoogleAPICallError) as e:
                last_error = e
                model_governance._stats["total_api_errors"] += 1

                if not model_governance.is_fallback_error(e):
                    # フォールバック対象外のエラー → そのまま raise
                    raise

                next_model = (
                    chain[i + 1] if i + 1 < len(chain) else None
                )

                if next_model:
                    model_governance._record_event(
                        "fallback_attempt", try_model, next_model,
                        self._caller, str(e),
                    )
                    logger.warning(
                        f"🛡️ ModelGovernance: '{try_model}' failed "
                        f"({self._classify_error(e)}), "
                        f"falling back to '{next_model}'"
                    )
                    time.sleep(model_governance.RETRY_DELAY_SECONDS)
                else:
                    # チェーン末端 → エラーを記録して raise
                    model_governance._record_event(
                        "fallback_exhausted", model, try_model,
                        self._caller, str(e),
                    )
                    logger.error(
                        f"🛡️ ModelGovernance: all models exhausted! "
                        f"chain={' → '.join(chain)}, "
                        f"last_error={self._classify_error(e)}"
                    )
                    raise

        raise last_error  # 到達しないはずだが安全のため

    def embed_content(self, *, model: str, contents: Any, **kwargs):
        """同期版: フォールバック付き embed_content"""
        # Layer 1: deprecated 差替
        model = model_governance.validate_and_correct(model, self._caller)

        # Layer 2: フォールバックチェーンを順に試行
        chain = model_governance.build_fallback_sequence(model)

        last_error = None
        for i, try_model in enumerate(chain):
            try:
                result = self._real.embed_content(model=try_model, contents=contents, **kwargs)

                if i > 0:
                    # フォールバックで成功した場合
                    model_governance._stats["fallback_activations"] += 1
                    model_governance._record_event(
                        "fallback_success", model, try_model,
                        self._caller,
                    )
                    logger.info(
                        f"🛡️ ModelGovernance: fallback success "
                        f"'{model}' → '{try_model}' (caller={self._caller})"
                    )

                return result

            except (APIError, GoogleAPICallError) as e:
                last_error = e
                model_governance._stats["total_api_errors"] += 1

                if not model_governance.is_fallback_error(e):
                    # フォールバック対象外のエラー → そのまま raise
                    raise

                next_model = (
                    chain[i + 1] if i + 1 < len(chain) else None
                )

                if next_model:
                    model_governance._record_event(
                        "fallback_attempt", try_model, next_model,
                        self._caller, str(e),
                    )
                    logger.warning(
                        f"🛡️ ModelGovernance: '{try_model}' failed "
                        f"({self._classify_error(e)}), "
                        f"falling back to '{next_model}'"
                    )
                    time.sleep(model_governance.RETRY_DELAY_SECONDS)
                else:
                    # チェーン末端 → エラーを記録して raise
                    model_governance._record_event(
                        "fallback_exhausted", model, try_model,
                        self._caller, str(e),
                    )
                    logger.error(
                        f"🛡️ ModelGovernance: all models exhausted! "
                        f"chain={' → '.join(chain)}, "
                        f"last_error={self._classify_error(e)}"
                    )
                    raise

        raise last_error  # 到達しないはずだが安全のため

    def _classify_error(self, error) -> str:
        """エラーを簡潔に分類"""
        s = str(error)
        if "429" in s or "RESOURCE_EXHAUSTED" in s:
            return "429:枠枯渇"
        if "503" in s or "UNAVAILABLE" in s:
            return "503:サーバー混雑"
        if "404" in s or "NOT_FOUND" in s:
            return "404:モデル不在"
        if "limit: 0" in s or "quota" in s:
            return "quota=0:利用不可"
        return f"unknown:{s[:60]}"

    def __getattr__(self, name):
        return getattr(self._real, name)


class GovernedAsyncModelsProxy:
    """client.aio.models の非同期プロキシ（フォールバック付き）"""

    def __init__(self, real_models, caller: str = ""):
        self._real = real_models
        self._caller = caller

    async def generate_content(self, *, model: str, **kwargs):
        """非同期版: フォールバック付き"""
        import asyncio

        model = model_governance.validate_and_correct(model, self._caller)
        chain = model_governance.build_fallback_sequence(model)

        last_error = None
        for i, try_model in enumerate(chain):
            try:
                result = await self._real.generate_content(
                    model=try_model, **kwargs,
                )
                if i > 0:
                    model_governance._stats["fallback_activations"] += 1
                    model_governance._record_event(
                        "fallback_success", model, try_model,
                        self._caller,
                    )
                    logger.info(
                        f"🛡️ Async fallback success: "
                        f"'{model}' → '{try_model}'"
                    )
                return result

            except (APIError, GoogleAPICallError) as e:
                last_error = e
                model_governance._stats["total_api_errors"] += 1

                if not model_governance.is_fallback_error(e):
                    raise

                next_model = (
                    chain[i + 1] if i + 1 < len(chain) else None
                )
                if next_model:
                    model_governance._record_event(
                        "fallback_attempt", try_model, next_model,
                        self._caller, str(e),
                    )
                    logger.warning(
                        f"🛡️ '{try_model}' failed, "
                        f"falling back to '{next_model}'"
                    )
                    await asyncio.sleep(
                        model_governance.RETRY_DELAY_SECONDS
                    )
                else:
                    model_governance._record_event(
                        "fallback_exhausted", model, try_model,
                        self._caller, str(e),
                    )
                    logger.error(
                        f"🛡️ All models exhausted: "
                        f"{' → '.join(chain)}"
                    )
                    raise

        raise last_error

    async def embed_content(self, *, model: str, contents: Any, **kwargs):
        """非同期版: フォールバック付き embed_content"""
        import asyncio

        model = model_governance.validate_and_correct(model, self._caller)
        chain = model_governance.build_fallback_sequence(model)

        last_error = None
        for i, try_model in enumerate(chain):
            try:
                result = await self._real.embed_content(
                    model=try_model, contents=contents, **kwargs,
                )
                if i > 0:
                    model_governance._stats["fallback_activations"] += 1
                    model_governance._record_event(
                        "fallback_success", model, try_model,
                        self._caller,
                    )
                    logger.info(
                        f"🛡️ Async fallback success: "
                        f"'{model}' → '{try_model}'"
                    )
                return result

            except (APIError, GoogleAPICallError) as e:
                last_error = e
                model_governance._stats["total_api_errors"] += 1

                if not model_governance.is_fallback_error(e):
                    raise

                next_model = (
                    chain[i + 1] if i + 1 < len(chain) else None
                )
                if next_model:
                    model_governance._record_event(
                        "fallback_attempt", try_model, next_model,
                        self._caller, str(e),
                    )
                    logger.warning(
                        f"🛡️ '{try_model}' failed, "
                        f"falling back to '{next_model}'"
                    )
                    await asyncio.sleep(
                        model_governance.RETRY_DELAY_SECONDS
                    )
                else:
                    model_governance._record_event(
                        "fallback_exhausted", model, try_model,
                        self._caller, str(e),
                    )
                    logger.error(
                        f"🛡️ All models exhausted: "
                        f"{' → '.join(chain)}"
                    )
                    raise

        raise last_error

    def __getattr__(self, name):
        return getattr(self._real, name)


def get_governed_client(caller: str = ""):
    """
    ガバナンス + 自動フォールバック付き Gemini Client を返す。

    通常の get_gemini_client() の代わりに使用することで:
      - deprecated モデルの自動差替
      - 429/503/404 エラー時の自動フォールバック
    が有効になる。

    Usage:
        from model_governance import get_governed_client
        client = get_governed_client("ai_proofreader")
        # model が枠枯渇でも自動的に次のモデルに切り替わる
        client.models.generate_content(model="gemini-3-flash-preview", ...)
    """
    from gemini_client_factory import _get_raw_client

    real_client = _get_raw_client()
    if real_client is None:
        return None

    class GovernedClient:
        def __init__(self, real):
            self._real = real
            self.models = GovernedModelsProxy(real.models, caller)

        def __getattr__(self, name):
            return getattr(self._real, name)

    return GovernedClient(real_client)


# ============================================================
# Harness Hook 統合
# ============================================================

async def _model_governance_hook(hook_input) -> None:
    """
    PreToolUse Hook: ツール引数内のモデル名を検証・是正。
    """
    tool_input = hook_input.tool_input or {}

    corrected_any = False
    updated = {}

    for key in ("model", "model_name", "MODEL_NAME"):
        if key in tool_input:
            original = tool_input[key]
            corrected = model_governance.validate_and_correct(
                original, f"hook:{hook_input.tool_name}"
            )
            if corrected != original:
                updated[key] = corrected
                corrected_any = True

    if corrected_any:
        from harness.hooks import HookOutput
        return HookOutput(updated_input=updated)

    return None


async def _model_usage_tracking_hook(hook_input) -> None:
    """
    PostToolUse Hook: API 呼び出し成功時にモデル使用量を自動カウント。

    ツールの入力引数に 'model' があれば使用量を記録する。
    これにより各コンポーネントで個別に usage_tracker.track_request() を
    呼ぶ必要がなくなる。
    """
    tool_input = hook_input.tool_input or {}
    model = (
        tool_input.get("model")
        or tool_input.get("model_name")
        or tool_input.get("MODEL_NAME")
    )
    if not model:
        return None

    try:
        from usage_tracker.tracker import usage_tracker
        result = usage_tracker.track_request(model)

        # 枠逼迫時のアラートを監査ログに記録
        if result.get("alert_level") in ("warning", "block", "critical"):
            model_governance._record_event(
                "quota_alert",
                model, model,
                f"hook:{hook_input.tool_name}",
                f"alert_level={result['alert_level']}, "
                f"usage={result['usage_ratio']:.1%}",
            )
    except (ImportError, AttributeError, TypeError, OSError) as e:
        logger.debug(f"Usage tracking skipped: {e}")

    return None


def register_governance_hook():
    """ハーネスの PreToolUse + PostToolUse に ModelGovernance Hook を登録"""
    try:
        from harness.hooks import hook_system, HookEvent

        # Layer 1: PreToolUse — deprecated差替 + フォールバック判定
        hook_system.register(
            HookEvent.PRE_TOOL_USE,
            callback=_model_governance_hook,
            priority=-10,
        )

        # Layer 4: PostToolUse — 使用量自動カウント
        hook_system.register(
            HookEvent.POST_TOOL_USE,
            callback=_model_usage_tracking_hook,
            priority=10,
        )

        logger.info(
            "🛡️ ModelGovernance Hooks registered "
            "(PreToolUse:deprecated差替, PostToolUse:使用量追跡)"
        )
    except ImportError:
        logger.debug("Harness not available, ModelGovernance Hooks skipped")


# ============================================================
# テスト
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("ModelGovernance — 3層防御テスト")
    print("=" * 60)

    stats = model_governance.get_stats()

    print(f"\n--- Layer 1: Deprecation Map ({stats['deprecation_corrections']} corrections) ---")
    for old, new in stats["deprecation_map"].items():
        print(f"  {old} → {new}")

    print(f"\n--- Layer 2: Fallback Chain ---")
    for model, fallback in stats["fallback_chain"].items():
        print(f"  {model} → {fallback or '(end)'}")

    # 差替テスト
    print("\n--- Deprecation Test ---")
    for m in ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.0-flash-lite"]:
        result = model_governance.validate_and_correct(m, "test")
        changed = " ← CORRECTED" if result != m else ""
        print(f"  {m} → {result}{changed}")

    # フォールバックチェーンテスト
    print("\n--- Fallback Chain Sequence ---")
    for start in ["gemini-3-flash-preview", "gemini-2.5-flash"]:
        seq = model_governance.build_fallback_sequence(start)
        print(f"  {start}: {' → '.join(seq)}")

    # 実 API テスト（フォールバック動作確認）
    print("\n--- Live API Fallback Test ---")
    import dotenv
    dotenv.load_dotenv()
    client = get_governed_client("test")
    if client:
        try:
            # deprecated モデルで呼び出し → 自動差替 + 成功
            r = client.models.generate_content(
                model="gemini-2.0-flash",
                contents="Say OK",
            )
            print(f"  ✅ deprecated model call succeeded: {r.text.strip()[:30]}")
        except (RuntimeError, ValueError) as e:
            print(f"  ❌ {e}")
    else:
        print("  ⚠️ No API key")

    print(f"\n--- Stats ---")
    final_stats = model_governance.get_stats()
    for k, v in final_stats.items():
        if k != "recent_events":
            print(f"  {k}: {v}")
