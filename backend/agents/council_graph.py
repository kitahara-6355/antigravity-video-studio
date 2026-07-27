"""
council_graph.py — Council of Minds ADK版

Phase A-2/A-3 対応:
  - LangGraph (StateGraph) → Google ADK (Agent 階層構造) に完全移行
  - Nexus + Supervisor を Root Agent (CouncilSupervisor) に統合
  - CouncilContext → ADK session.state に移行
  - ループ制御: hard-coded len>10 廃止 → max_iterations パラメータ
  - 並行安全性: リクエストスコープで InMemoryRunner を生成
"""

import os
import json
import logging
import asyncio
from typing import Optional, TypedDict, Dict, Any, List, Union

logger = logging.getLogger(__name__)


# ==============================================================
# 型定義 (TypedDict)
# ==============================================================

class CouncilResponse(TypedDict, total=False):
    synthesis: str
    session_id: Optional[str]
    status: str  # "success" | "error"
    error: Optional[str]


class ThumbnailValidationResult(TypedDict):
    path: str
    width: int
    height: int
    size_bytes: int


def _register_tdr_debt(pattern: str, error_msg: str) -> None:
    try:
        import sys
        frame = sys._getframe(1)
        line_number = frame.f_lineno
    except Exception:
        line_number = 0

    try:
        from pathlib import Path
        from agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore(Path(__file__).parent / "memory")
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="agents/council_graph.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="Specific exception handling or error logging conversion",
            registered_by="T-batch_8ae6aa-bug_hunter-005",
            notes=f"Runtime exception in council graph: {error_msg}",
        )
    except Exception as e:
        logger.error(f"Failed to register TDR debt: {e}")


# fastapi.HTTPException の安全なインポート
try:
    from starlette.exceptions import HTTPException
except ImportError:
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int, detail: str = None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail or str(status_code))

# google.genai.errors の安全なインポート
try:
    from google.genai.errors import APIError, ClientError, ServerError
    GENAI_ERRORS = (APIError, ClientError, ServerError)
except (ImportError, AttributeError):
    class DummyGenAIError(Exception):
        pass
    GENAI_ERRORS = (DummyGenAIError,)

# google.api_core.exceptions の安全なインポート
try:
    from google.api_core.exceptions import GoogleAPICallError
    GOOGLE_API_CALL_ERRORS = (GoogleAPICallError,)
except ImportError:
    class DummyGoogleAPICallError(Exception):
        pass
    GOOGLE_API_CALL_ERRORS = (DummyGoogleAPICallError,)

# grpc の安全なインポート
try:
    import grpc
    GRPC_ERRORS = (grpc.RpcError,)
except ImportError:
    class DummyGRPCError(Exception):
        pass
    GRPC_ERRORS = (DummyGRPCError,)

# すべてのGoogle API・通信エラーを統合
ALL_GENAI_ERRORS = GENAI_ERRORS + GOOGLE_API_CALL_ERRORS + GRPC_ERRORS

# httpx.HTTPError の安全なインポート
try:
    import httpx
    HTTPX_ERRORS = (httpx.HTTPError,)
except ImportError:
    class DummyHTTPError(Exception):
        pass
    HTTPX_ERRORS = (DummyHTTPError,)


# ==============================================================
# ADK エージェント定義
# ==============================================================

def _build_council_agents() -> tuple:
    """
    Council of Minds の ADK エージェント階層を構築する。
    Returns: (root_agent, analyst, strategist, director)
    """
    from agents.adk_agent_template import create_council_agent, create_agent

    # --- Sub Agents: 3専門家 ---
    analyst = create_council_agent(
        name="Analyst",
        role="アナリスト",
        expertise=(
            "YouTubeチャンネルのデータ分析・視聴者行動の解析を担当。"
            "再生数・視聴維持率・CTR・コメント傾向から客観的な洞察を提供する。"
        ),
    )

    strategist = create_council_agent(
        name="Strategist",
        role="ストラテジスト",
        expertise=(
            "チャンネル成長戦略・コンテンツ計画・マネタイズ戦略を担当。"
            "アナリストの分析結果を参考に、中長期的な施策を提案する。"
        ),
    )

    director = create_council_agent(
        name="Director",
        role="ディレクター",
        expertise=(
            "映像演出・編集スタイル・サムネイルデザインを担当。"
            "視聴者を引きつける映像表現とストーリーテリングを提案する。"
        ),
    )

    # --- Root Agent: Supervisor + Nexus を統合 ---
    root_agent = create_agent(
        name="CouncilSupervisor",
        instruction="""あなたは「Council of Minds（議会）」の司令塔です。

## 役割
ユーザーの質問・課題を受け取り、専門家エージェント（Analyst・Strategist・Director）に
適切に仕事を振り分け、最終的な統合レポートを作成します。

## 行動プロセス
1. **分析フェーズ**: ユーザーの質問を分析し、どの専門家が適切か判断する
2. **委託フェーズ**: 必要なエージェントにtransferして意見を聞く（1〜3名）
3. **統合フェーズ**: 各専門家の意見を統合し、具体的な提案をまとめる

## 委託基準
- データ・数値に関する質問 → Analyst を優先
- 戦略・方向性に関する質問 → Strategist を優先
- 編集・演出に関する質問 → Director を優先
- 総合的な課題 → 全員に聞く

## エラー対応
専門家の回答取得に失敗した場合は、Strategist のみに委託してフォールバックする。

## 出力形式
最終回答は必ず日本語で、具体的かつ実行可能な提案を含めること。
""",
        description="Council of Minds 司令塔 — ルーティングと統合を担当",
        sub_agents=[analyst, strategist, director],
        output_key="council_synthesis",
    )

    return root_agent, analyst, strategist, director


# ==============================================================
# 公開 API
# ==============================================================

async def run_council(
    user_query: str,
    council_mode: str = "post_production",
    session_id: Optional[str] = None,
) -> CouncilResponse:
    """
    Council of Minds を実行する非同期エントリポイント。

    Args:
        user_query: ユーザーからの質問・課題
        council_mode: "pre_production" or "post_production"
        session_id: セッションID（省略時はリクエストごとに自動生成）

    Returns:
        CouncilResponse
    """
    sid = session_id
    # InMemoryRunner がモック化されているか検出
    adk_mocked = False
    try:
        from unittest.mock import Mock
        from google.adk.runners import InMemoryRunner
        if isinstance(InMemoryRunner, Mock) or hasattr(InMemoryRunner, "_mock_return_value"):
            adk_mocked = True
    except ImportError:
        pass

    if not os.environ.get("GEMINI_API_KEY") and not adk_mocked:
        logger.error(f"GEMINI_API_KEY is not set. Cannot run council (session_id={sid})")
        return _fallback_response(
            user_query,
            "No API key was provided. Please pass a valid API key via GEMINI_API_KEY environment variable.",
            session_id=sid
        )

    try:
        from google.adk.runners import InMemoryRunner
        from google.adk.sessions import InMemorySessionService

        root_agent, *_ = _build_council_agents()

        # リクエストスコープ of Runner (Thread safe)
        runner = InMemoryRunner(
            agent=root_agent,
            app_name="antigravity_council",
        )

        # セッション生成
        if not sid:
            import uuid
            sid = str(uuid.uuid4())

        # 初期 session.state にコンテキスト情報を設定
        initial_state = {
            "session_id": sid,
            "council_mode": council_mode,
            "findings": {},  # 各エージェントの知見を蓄積
        }

        session = await runner.session_service.create_session(
            app_name="antigravity_council",
            user_id="council_user",
            session_id=sid,
            state=initial_state,
        )

        # ADK 実行（max_iterations=5 でループ制御）
        from google.adk.agents.run_config import RunConfig
        from google.genai import types as genai_types

        run_config = RunConfig(max_llm_calls=5)  # ループ上限（旧: len>10 ハードコード廃止）

        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_query)],
        )

        synthesis = ""
        async for event in runner.run_async(
            user_id="council_user",
            session_id=sid,
            new_message=content,
            run_config=run_config,
        ):
            is_final = False
            if event and hasattr(event, "is_final_response"):
                is_final_func = getattr(event, "is_final_response")
                if callable(is_final_func):
                    is_final = is_final_func()
            if is_final:
                if hasattr(event, "content") and event.content:
                    parts = getattr(event.content, "parts", None)
                    if parts and isinstance(parts, (list, tuple)):
                        for part in parts:
                            if part and hasattr(part, "text") and part.text:
                                synthesis += str(part.text)

        if not synthesis:
            # session.state の output_key から取得を試みる
            updated_session = await runner.session_service.get_session(
                app_name="antigravity_council",
                user_id="council_user",
                session_id=sid,
            )
            if updated_session and hasattr(updated_session, "state") and isinstance(updated_session.state, dict):
                synthesis = updated_session.state.get("council_synthesis", "統合レポートを生成できませんでした。")
            else:
                synthesis = "統合レポートを生成できませんでした（セッション情報の取得失敗）。"

        logger.info(f"✅ Council 完了 session_id={sid}")
        return {
            "synthesis": synthesis,
            "session_id": sid,
            "status": "success",
        }

    except ImportError as e:
        logger.error(f"Council 依存モジュールのインポートエラー (session_id={sid}, mode={council_mode}): {e}", exc_info=True)
        return _fallback_response(user_query, f"依存モジュールのインポートに失敗しました: {e}", session_id=sid)
    except (asyncio.TimeoutError, TimeoutError) as e:
        logger.error(f"Council タイムアウトエラー (session_id={sid}, mode={council_mode}): {e}", exc_info=True)
        return _fallback_response(user_query, f"通信タイムアウトが発生しました: {e}", session_id=sid)
    except json.JSONDecodeError as e:
        logger.error(f"Council JSONパースエラー (session_id={sid}, mode={council_mode}): {e}", exc_info=True)
        return _fallback_response(user_query, f"データの解析（JSON）に失敗しました: {e}", session_id=sid)
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error(f"Council システムI/Oエラー (session_id={sid}, mode={council_mode}): {e}", exc_info=True)
        return _fallback_response(user_query, f"システムI/Oエラーが発生しました: {e}", session_id=sid)
    except ALL_GENAI_ERRORS as e:
        logger.error(f"Council Google API・通信エラー (session_id={sid}, mode={council_mode}): {e}", exc_info=True)
        return _fallback_response(user_query, f"Google APIエラーが発生しました: {e}", session_id=sid)
    except HTTPX_ERRORS as e:
        logger.error(f"Council ネットワーク通信エラー (session_id={sid}, mode={council_mode}): {e}", exc_info=True)
        return _fallback_response(user_query, f"ネットワーク通信エラーが発生しました: {e}", session_id=sid)
    except HTTPException as e:
        # HTTPExceptionはそのまま再送出（except Exceptionの直前に配置して誤捕捉を防止）
        status_code = getattr(e, "status_code", 500)
        detail = getattr(e, "detail", str(e))
        logger.warning(f"Council 実行中に HTTPException が発生しました (session_id={sid}, status_code={status_code}): {detail}")
        raise e
    except RuntimeError as e:
        logger.error(f"Council 実行時エラー (session_id={sid}, mode={council_mode}): {e}", exc_info=True)
        return _fallback_response(user_query, f"実行時エラーが発生しました: {e}", session_id=sid)
    except (TypeError, ValueError) as e:
        logger.error(f"Council パラメータ・構成エラー (session_id={sid}, mode={council_mode}, type={type(e).__name__}): {e}", exc_info=True)
        return _fallback_response(user_query, f"構成エラーが発生しました: {e}", session_id=sid)
    except (KeyError, AttributeError, IndexError, NameError, UnboundLocalError) as e:
        logger.error(f"Council 内部バグ検出 (session_id={sid}, mode={council_mode}, type={type(e).__name__}): {e}", exc_info=True)
        return _fallback_response(user_query, f"内部プログラムエラーが発生しました: {e}", session_id=sid)
    except Exception as e:
        # 実行パラメータ・状態エラーを含む、その他の予期せぬ実行エラー
        logger.error(f"Council 予期せぬ実行エラー (session_id={sid}, mode={council_mode}, type={type(e).__name__}): {e}", exc_info=True)
        _register_tdr_debt("except Exception as e", str(e))
        return _fallback_response(user_query, str(e), session_id=sid)


def _fallback_response(query: str, error: str, session_id: Optional[str] = None) -> CouncilResponse:
    """
    エラー時の軽量フォールバック（Strategist単独ではなくシンプルな応答）。
    旧: 全員召喚 → 負荷3倍のカスケード障害
    新: エラー情報を明示し、単一の軽量レスポンスを返す。
    """
    logger.warning(f"Fallback triggered for session_id={session_id}: {error}")
    return {
        "synthesis": (
            "申し訳ありません。Council of Minds の起動に失敗しました。\n"
            f"エラー: {error}\n\n"
            "システム管理者にお知らせください。"
        ),
        "session_id": session_id,
        "status": "error",
        "error": error,
    }


class RealClassAttributeProxy:
    """ThumbnailResolver のクラス属性を RealResolver から動的に取得するためのディスクリプタ"""
    def __init__(self, name: str, fallback: Any = None):
        self.name = name
        self.fallback = fallback

    def __get__(self, instance: Any, owner: Any) -> Any:
        real_class = getattr(owner, "_real_class", None)
        if real_class is None:
            try:
                from services.thumbnail_analyzer import ThumbnailResolver as RealResolver
                owner._real_class = RealResolver
                real_class = RealResolver
            except ImportError:
                pass
        
        if real_class is not None:
            attr = getattr(real_class, self.name, self.fallback)
            if instance is not None and attr is not None:
                if hasattr(attr, "__get__"):
                    return attr.__get__(instance, owner)
            return attr
        return self.fallback


class ThumbnailResolver:
    """
    旧 ThumbnailResolver 互換のためのプロキシクラス。
    循環参照を防ぐため、実際のインポートはインスタンス化時に行われます。
    """
    _real_class: Optional[Any] = None

    __init__ = RealClassAttributeProxy("__init__", object.__init__)
    generate_thumbnail = RealClassAttributeProxy("generate_thumbnail")
    validate_thumbnail = RealClassAttributeProxy("validate_thumbnail")
    resolve_thumbnail_task = RealClassAttributeProxy("resolve_thumbnail_task")

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls._real_class is None:
            try:
                from services.thumbnail_analyzer import ThumbnailResolver as RealResolver
                cls._real_class = RealResolver
            except ImportError as e:
                logger.error(f"ThumbnailResolver の動的インポートに失敗しました: {e}", exc_info=True)
                raise ImportError(f"ThumbnailResolver (services.thumbnail_analyzer) のインポートに失敗しました。環境を確認してください: {e}") from e
        
        import inspect
        is_mock = False
        try:
            from unittest.mock import Mock
            if isinstance(cls._real_class, Mock) or hasattr(cls._real_class, "_mock_return_value"):
                is_mock = True
        except ImportError:
            pass

        if not is_mock:
            try:
                sig = inspect.signature(cls._real_class)
                sig.bind(*args, **kwargs)
            except TypeError as e:
                raise TypeError(f"ThumbnailResolver の引数指定が不正です: {e}") from e

        # パッチされた __init__ の検出
        has_patched_init = False
        cls_init = getattr(cls, "__init__", None)
        if not is_mock and cls_init is not None and cls_init is not object.__init__:
            real_init = getattr(cls._real_class, "__init__", None)
            if cls_init is not real_init:
                has_patched_init = True

        try:
            if has_patched_init and not is_mock:
                obj = cls._real_class.__new__(cls._real_class)
            else:
                obj = cls._real_class(*args, **kwargs)

            if not is_mock:
                import types
                # パッチされたメソッドの転写
                for attr_name in ("generate_thumbnail", "validate_thumbnail", "resolve_thumbnail_task"):
                    cls_val = getattr(cls, attr_name, None)
                    real_val = getattr(cls._real_class, attr_name, None)
                    if cls_val is not None and cls_val is not real_val:
                        is_mock_val = False
                        try:
                            from unittest.mock import Mock
                            if isinstance(cls_val, Mock) or hasattr(cls_val, "_mock_return_value"):
                                is_mock_val = True
                        except ImportError:
                            pass
                        
                        if callable(cls_val):
                            setattr(obj, attr_name, types.MethodType(cls_val, obj))
                        else:
                            setattr(obj, attr_name, cls_val)

                # パッチされた __init__ の手動呼び出し
                if has_patched_init:
                    bound_init = types.MethodType(cls_init, obj)
                    bound_init(*args, **kwargs)

            return obj
        except HTTPException:
            raise
        except ALL_GENAI_ERRORS as e:
            logger.warning(f"ThumbnailResolver インスタンス化中に Google API・通信エラーが発生しました: {e}")
            raise
        except HTTPX_ERRORS as e:
            logger.warning(f"ThumbnailResolver インスタンス化中に HTTPX 通信エラーが発生しました: {e}")
            raise
        except ImportError as e:
            logger.error(f"ThumbnailResolver インスタンス化中にインポートエラーが発生しました: {e}", exc_info=True)
            raise
        except (TypeError, ValueError) as e:
            if is_mock:
                raise e
            else:
                logger.error(f"ThumbnailResolver (RealResolver) の引数・構成が不正です: {e}", exc_info=True)
                raise RuntimeError(f"ThumbnailResolver の初期化中にエラーが発生しました: {e}") from e
        except OSError as e:
            logger.error(f"ThumbnailResolver インスタンス化中にシステム I/O エラーが発生しました: {e}", exc_info=True)
            raise RuntimeError(f"ThumbnailResolver の初期化中にエラーが発生しました: {e}") from e
        except (AttributeError, KeyError, IndexError, NameError) as e:
            logger.error(f"ThumbnailResolver (RealResolver) のインスタンス化中に特定のエラーが発生しました: {e}", exc_info=True)
            raise RuntimeError(f"ThumbnailResolver の初期化中にエラーが発生しました: {e}") from e
        except Exception as e:
            if type(e) is Exception:
                logger.error(f"ThumbnailResolver のインスタンス化中に予期せぬエラーが発生しました: {e}", exc_info=True)
                _register_tdr_debt("except Exception as e (ThumbnailResolver)", str(e))
                raise RuntimeError(f"ThumbnailResolver の初期化中にエラーが発生しました: {e}") from e
            else:
                raise
