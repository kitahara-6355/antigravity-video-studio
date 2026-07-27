"""
adk_bridge.py — Harness ↔ Google ADK 統合ブリッジ

アーキテクチャ監査で検出された3つの構造的問題を解消:
  1. 二重実行パス → ADK SequentialAgent を唯一の実行パスに
  2. ツール二重定義 → ToolRegistry を Single Source of Truth に
  3. ADK 実行時の Hook 無効 → HookRunner で全実行をラップ

設計:
  ToolRegistry に登録されたツールを ADK Agent 互換の関数に変換し、
  実行時に自動で Hook 発火 + ガバナンスチェック + セッション記録を行う。

Usage:
  from harness.adk_bridge import build_harness_pipeline, run_harness_pipeline

  # Harness 統合済み ADK パイプラインを構築・実行
  result = await run_harness_pipeline(video_path="/path/to/video.mp4")
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# 1. ToolRegistry → ADK 互換ツール変換のヘルパー関数群
# ============================================================

async def _execute_adk_tool_pre_check(
    tool_name: str,
    kwargs: Dict[str, Any],
    session_id: str,
    agent_scope: str,
) -> Optional[str]:
    """PreToolUse Hook とガバナンス権限チェックを実行する。拒否された場合はエラーメッセージを返す。"""
    from harness.hooks import hook_system, HookEvent, HookInput
    from harness.governance import governance_engine

    # --- PreToolUse Hook ---
    pre_input = HookInput(
        tool_name=tool_name,
        tool_input=kwargs,
        session_id=session_id,
        agent_id=agent_scope,
    )
    pre_output = await hook_system.fire(HookEvent.PRE_TOOL_USE, pre_input)

    if pre_output.permission_decision == "deny":
        reason = pre_output.permission_decision_reason or "Hook により拒否"
        logger.warning(f"🚫 Hook denied: {tool_name} — {reason}")
        return json.dumps({
            "success": False,
            "error": f"実行拒否: {reason}",
        }, ensure_ascii=False)

    # 入力の上書き（Hook で変更された場合）
    if pre_output.updated_input:
        kwargs.update(pre_output.updated_input)

    # --- ガバナンス権限チェック ---
    if agent_scope:
        allowed = governance_engine.check_permission(agent_scope, tool_name)
        if not allowed:
            msg = f"権限不足: {agent_scope} → {tool_name}"
            logger.warning(f"🚫 {msg}")
            return json.dumps({"success": False, "error": msg}, ensure_ascii=False)

    return None


async def _handle_adk_tool_post_success(
    tool_name: str,
    kwargs: Dict[str, Any],
    session_id: str,
    agent_scope: str,
    span_id: str,
    result: Any,
    duration: float,
) -> None:
    """ツール実行が正常に終了した際の Hook 発火、セッション記録、スパンクローズを行う。"""
    from harness.hooks import hook_system, HookEvent, HookInput
    from harness.governance import governance_engine
    from harness.session_manager import session_manager

    post_input = HookInput(
        tool_name=tool_name,
        tool_output=result.content,
        session_id=session_id,
        agent_id=agent_scope,
    )
    await hook_system.fire(HookEvent.POST_TOOL_USE, post_input)

    # セッション記録
    if session_id:
        session_manager.record_tool_call(
            session_id, tool_name,
            kwargs, result.content, duration,
        )

    governance_engine.end_span(span_id, status="ok")


async def _handle_adk_tool_post_failure(
    tool_name: str,
    session_id: str,
    agent_scope: str,
    span_id: str,
    result: Any,
) -> None:
    """ツール実行結果がエラーを返した際の Hook 発火、スパンクローズを行う。"""
    from harness.hooks import hook_system, HookEvent, HookInput
    from harness.governance import governance_engine

    error_text = result.content[0].get("text", "") if result.content else ""
    fail_input = HookInput(
        tool_name=tool_name,
        error=error_text,
        session_id=session_id,
        agent_id=agent_scope,
    )
    await hook_system.fire(HookEvent.POST_TOOL_USE_FAILURE, fail_input)
    governance_engine.end_span(span_id, status="error")


async def _handle_adk_tool_exception(
    tool_name: str,
    session_id: str,
    span_id: str,
    exc: Exception,
) -> str:
    """ツール実行中に例外が発生した際の Hook 発火、スパンクローズ、エラーレスポンス返却を行う。"""
    from harness.hooks import hook_system, HookEvent, HookInput
    from harness.governance import governance_engine

    governance_engine.end_span(span_id, status="error")

    fail_input = HookInput(
        tool_name=tool_name,
        error=str(exc),
        session_id=session_id,
    )
    await hook_system.fire(HookEvent.POST_TOOL_USE_FAILURE, fail_input)

    return json.dumps({
        "success": False,
        "error": str(exc)[:500],
    }, ensure_ascii=False)


# ============================================================
# 2. ToolRegistry → ADK 互換ツール変換
# ============================================================

def create_adk_tool_from_registry(
    tool_name: str,
    agent_scope: str = "",
) -> Callable:
    """
    ToolRegistry に登録されたツールを ADK Agent 互換の関数に変換。

    変換時に以下を自動注入:
      - PreToolUse Hook 発火（ディスクガード等）
      - ガバナンス権限チェック（caller_scopes）
      - PostToolUse / PostToolUseFailure Hook 発火
      - セッション記録

    Args:
        tool_name: ToolRegistry 上のツール名
        agent_scope: 呼び出し元エージェントのガバナンススコープ

    Returns:
        ADK Agent の tools= に渡せる async 関数
    """
    from harness.tool_registry import tool_registry

    tool_def = tool_registry.get_tool(tool_name)
    if not tool_def:
        raise ValueError(f"ToolRegistry にツール '{tool_name}' が未登録")

    async def _adk_tool_wrapper(**kwargs) -> str:
        """
        ADK Agent から呼ばれる関数。
        ToolRegistry.execute() + Hook + Governance を統合実行。
        """
        from harness.tool_registry import tool_registry
        from harness.governance import governance_engine

        # セッションID取得（ADK session.state から）
        session_id = kwargs.pop("_session_id", "")

        # --- 事前チェック ---
        deny_response = await _execute_adk_tool_pre_check(
            tool_name, kwargs, session_id, agent_scope
        )
        if deny_response is not None:
            return deny_response

        # --- トレーススパン開始 ---
        span_id = governance_engine.start_span(
            operation="adk_tool_call",
            tool_name=tool_name,
        )

        # --- ToolRegistry 経由で実行 ---
        start_time = time.time()
        try:
            result = await tool_registry.execute(tool_name, kwargs)
            duration = round(time.time() - start_time, 2)

            if not result.is_error:
                # --- 正常終了時の処理 ---
                await _handle_adk_tool_post_success(
                    tool_name, kwargs, session_id, agent_scope, span_id, result, duration
                )
            else:
                # --- エラー終了時の処理 ---
                await _handle_adk_tool_post_failure(
                    tool_name, session_id, agent_scope, span_id, result
                )

            # ADK は文字列を返す必要がある
            return result.content[0].get("text", "") if result.content else ""

        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError, asyncio.TimeoutError) as e:
            return await _handle_adk_tool_exception(tool_name, session_id, span_id, e)

    # ADK が __name__ と __doc__ からスキーマを生成するため保持
    _adk_tool_wrapper.__name__ = tool_name
    _adk_tool_wrapper.__doc__ = tool_def.description
    # ADK の型ヒント用にアノテーションを設定
    _adk_tool_wrapper.__annotations__ = _build_annotations(tool_def.input_schema)

    return _adk_tool_wrapper


def _build_annotations(input_schema: Dict) -> Dict:
    """ToolRegistry の input_schema → Python 型アノテーションに変換"""
    annotations = {}
    type_map = {str: str, int: int, float: float, bool: bool, list: list, dict: dict}

    for key, val in input_schema.items():
        if isinstance(val, dict):
            py_type = val.get("type", str)
        else:
            py_type = val if isinstance(val, type) else str
        annotations[key] = type_map.get(py_type, str)

    annotations["return"] = str
    return annotations


# ============================================================
# 3. Harness統合済み ADK パイプラインビルダー
# ============================================================

def build_harness_pipeline(model_override: str = None):
    """
    Harness 統合済みの ADK ProductionPipeline を構築。

    ToolRegistry のツールを ADK Agent の tools として使用し、
    二重定義を解消。各 Agent にガバナンススコープを付与。

    Returns:
        (SequentialAgent, tool_map) — パイプラインとツール参照
    """
    from google.adk.agents import Agent, SequentialAgent, LoopAgent
    from harness.pipeline_tools import register_pipeline_tools
    from harness.tool_registry import tool_registry

    # ToolRegistry にツールを登録（未登録の場合）
    if not tool_registry.get_tool("transcribe_video"):
        register_pipeline_tools()

    # --- VerifiedFacts コンテキスト取得 ---
    facts_preamble = ""
    try:
        from agents.memory.verified_facts import verified_facts_store
        ctx = verified_facts_store.get_facts_for_context(max_tokens=500)
        if ctx:
            facts_preamble = f"\n\n## プロジェクト確定仕様\n{ctx}\n\n"
    except (ImportError, Exception):
        pass

    # --- モデル取得（フォールバックチェーン対応）---
    if model_override:
        model = model_override
    else:
        try:
            from model_registry import get_model
            model = get_model("supervisor")
        except ImportError:
            model = "gemini-2.5-flash"

    # --- ToolRegistry → ADK 互換ツールに変換（Hook + Governance 注入済み） ---
    transcribe_tool = create_adk_tool_from_registry("transcribe_video", "transcriber")
    proofread_tool = create_adk_tool_from_registry("proofread_subtitles", "proofreader")
    smartcut_tool = create_adk_tool_from_registry("propose_smart_cut", "optimizer")
    preview_tool = create_adk_tool_from_registry("generate_preview", "renderer")
    quality_tool = create_adk_tool_from_registry("check_quality", "quality_gate")
    youtube_tool = create_adk_tool_from_registry("optimize_youtube", "optimizer")
    render_tool = create_adk_tool_from_registry("render_final", "renderer")

    # --- ADK Agent 定義 ---
    transcribe_agent = Agent(
        name="TranscribeAgent",
        model=model,
        instruction=(
            "あなたは音声認識担当です。"
            "指定された動画ファイルの文字起こしを実行してください。"
            "transcribe_video ツールを使い、結果を報告してください。"
        ),
        tools=[transcribe_tool],
        description="Stage 1: 音声認識（faster-whisper）",
    )

    proofread_agent = Agent(
        name="ProofreadAgent",
        model=model,
        instruction=(
            "あなたは校閲担当です。"
            "前のステージで生成された字幕テキストのAI校閲を実行してください。"
            f"proofread_subtitles ツールを使い、固有名詞修正と文法チェックを行ってください。{facts_preamble}"
        ),
        tools=[proofread_tool],
        description="Stage 2: AI校閲（Gemini + 固有名詞辞書）",
    )

    smartcut_agent = Agent(
        name="SmartCutAgent",
        model=model,
        instruction=(
            "あなたは構成エディターです。"
            "校閲済み字幕データから SmartCut 構成案を生成してください。"
            "propose_smart_cut ツールを使い、デフォルト20分版の構成を提案してください。"
        ),
        tools=[smartcut_tool],
        description="Stage 3: SmartCut構成",
    )

    preview_agent = Agent(
        name="PreviewAgent",
        model=model,
        instruction=(
            "あなたはプレビュー担当です。"
            "確定した構成でプレビュー動画を生成してください。"
            "generate_preview ツールを使ってください。"
        ),
        tools=[preview_tool],
        description="Stage 4: プレビュー生成（FFmpeg + GPU）",
    )

    quality_agent = Agent(
        name="QualityGateAgent",
        model=model,
        instruction=(
            "あなたは品質管理担当です。"
            "プレビュー動画の品質チェックを実行してください。"
            "check_quality ツールを使い、80点以上なら合格、未満なら修正が必要です。"
            f"\n合格の場合: 「PASSED」と報告\n不合格の場合: 具体的な改善点を報告{facts_preamble}"
        ),
        tools=[quality_tool],
        description="Stage 5: 品質チェック（Quality Gate）",
    )

    render_agent = Agent(
        name="RenderAgent",
        model=model,
        instruction=(
            "あなたはレンダリング担当です。"
            "品質チェック合格後、最終レンダリングを実行してください。"
            "render_final ツールを使ってください。"
        ),
        tools=[render_tool],
        description="Stage 6: 最終レンダリング",
    )

    youtube_agent = Agent(
        name="YouTubeOptAgent",
        model=model,
        instruction=(
            "あなたはYouTube最適化担当です。"
            "完成した動画の字幕テキストから、YouTube投稿用のメタデータを生成してください。"
            "optimize_youtube ツールを使ってください。"
        ),
        tools=[youtube_tool],
        description="Stage 7: YouTube最適化（SEO + チャプター）",
    )

    # --- 修正ループ（プレビュー → 品質チェックの反復） ---
    review_loop = LoopAgent(
        name="ReviewLoop",
        sub_agents=[preview_agent, quality_agent],
        max_iterations=3,
    )

    # --- メインパイプライン ---
    pipeline = SequentialAgent(
        name="HarnessProductionPipeline",
        sub_agents=[
            transcribe_agent,    # ① 文字起こし
            proofread_agent,     # ② AI校閲
            smartcut_agent,      # ③ 構成決定
            review_loop,         # ④⑤ プレビュー＆品質ループ
            render_agent,        # ⑥ レンダリング
            youtube_agent,       # ⑦ YouTube最適化
        ],
    )

    logger.info(
        "✅ HarnessProductionPipeline built: "
        "7 agents, ReviewLoop (max 3 iterations), "
        "Harness integration (Hook + Governance + Session)"
    )

    return pipeline


# ============================================================
# 4. Harness 統合実行のヘルパー関数群
# ============================================================

async def _execute_pipeline_loop(
    runner: Any,
    sid: str,
    content: Any,
    run_config: Any,
    harness_sid: str,
) -> str:
    """runner を実行し、生成されたテキストを結合して返す。"""
    from harness.session_manager import session_manager

    result_text = ""
    async for event in runner.run_async(
        user_id="pipeline_user",
        session_id=sid,
        new_message=content,
        run_config=run_config,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    result_text += part.text

        # Harness セッションのステージ進捗更新
        if hasattr(event, 'author') and event.author:
            session_manager.update_stage(
                harness_sid,
                stage=0,
                detail=f"Agent: {event.author}",
            )
    return result_text


async def _handle_pipeline_fallback(
    e: Exception,
    video_path: str,
    target_minutes: int,
    session_id: Optional[str],
    _fallback_model: Optional[str],
    _fallback_attempt: int,
    _max_fallback_attempts: int,
    fallback_chain: List[str],
    pipeline: Any,
    trace_span: str,
    total_start: float,
    harness_sid: str,
    sid: str,
) -> dict:
    """API エラーなどのフォールバックチェーン処理、または通常エラーのハンドリングを行う。"""
    from harness.hooks import hook_system, HookEvent, HookInput
    from harness.governance import governance_engine
    from harness.session_manager import session_manager
    from model_governance import model_governance as _mg

    error_str = str(e)

    # model_governance の統一判定でフォールバック対象か判定
    if _mg.is_fallback_error(e):
        # 503 UNAVAILABLE は一時的な混雑 → 同モデルでリトライ（最大2回待機）
        is_503 = "503" in error_str or "UNAVAILABLE" in error_str
        if is_503 and _fallback_attempt < 2:
            wait_sec = 10 * (_fallback_attempt + 1)  # 10s, 20s
            logger.warning(
                f"🛡️ 503 UNAVAILABLE detected (attempt {_fallback_attempt + 1}/2), "
                f"waiting {wait_sec}s before retry with same model..."
            )
            governance_engine.end_span(trace_span, status="retry_503")
            await asyncio.sleep(wait_sec)
            return await run_harness_pipeline(
                video_path=video_path,
                target_minutes=target_minutes,
                session_id=session_id,
                _fallback_model=_fallback_model,  # 同じモデルでリトライ
                _fallback_attempt=_fallback_attempt + 1,
                _max_fallback_attempts=_max_fallback_attempts,
            )

        # 最大試行回数を超えた場合は上位にフォールバックを委ねる
        if _fallback_attempt >= _max_fallback_attempts:
            logger.warning(
                f"🛡️ Fallback max retries ({_max_fallback_attempts}) exceeded, "
                f"raising to pipeline_router for legacy fallback"
            )
            governance_engine.end_span(trace_span, status="exhausted")
            raise RuntimeError(f"API Error: 全フォールバック枯渇 (試行{_fallback_attempt}回) — {error_str[:100]}")

        current_idx = 0
        current_model = pipeline.model if hasattr(pipeline, 'model') else fallback_chain[0]
        for i, m in enumerate(fallback_chain):
            if m == current_model:
                current_idx = i
                break

        next_idx = current_idx + 1
        if next_idx < len(fallback_chain):
            next_model = fallback_chain[next_idx]
            logger.warning(
                f"🛡️ API error detected (attempt {_fallback_attempt + 1}/{_max_fallback_attempts}), "
                f"retrying with fallback: {fallback_chain[current_idx]} → {next_model}"
            )
            governance_engine.end_span(trace_span, status="fallback")

            # フォールバックモデルで再帰的にリトライ
            await asyncio.sleep(3)  # クォータリセット待ち
            return await run_harness_pipeline(
                video_path=video_path,
                target_minutes=target_minutes,
                session_id=session_id,
                _fallback_model=next_model,
                _fallback_attempt=_fallback_attempt + 1,
                _max_fallback_attempts=_max_fallback_attempts,
            )
        else:
            # チェーン末端到達 → 即raise
            logger.warning("🛡️ Fallback chain exhausted, raising to pipeline_router")
            governance_engine.end_span(trace_span, status="exhausted")
            raise RuntimeError(f"API Error: フォールバックチェーン枯渇")

    # 通常のエラー処理
    duration = round(time.time() - total_start, 1)
    governance_engine.end_span(trace_span, status="error")
    session_manager.error_session(harness_sid, error_str)

    await hook_system.fire(
        HookEvent.SESSION_END,
        HookInput(
            tool_name="HarnessProductionPipeline",
            session_id=harness_sid,
            metadata={"duration_seconds": duration, "status": "error", "error": error_str},
        ),
    )

    logger.error(f"HarnessProductionPipeline error: {e}", exc_info=True)
    return {
        "status": "error",
        "session_id": sid,
        "harness_session_id": harness_sid,
        "error": error_str,
        "duration_seconds": duration,
    }


# ============================================================
# 5. Harness 統合実行エントリポイント
# ============================================================

async def run_harness_pipeline(
    video_path: str,
    target_minutes: int = 20,
    session_id: Optional[str] = None,
    _fallback_model: Optional[str] = None,
    _fallback_attempt: int = 0,
    _max_fallback_attempts: int = 3,
) -> dict:
    """
    Harness 統合済み ADK パイプラインを実行。

    従来の2系統（PipelineCoordinator / ProductionPipeline）を統合し、
    単一の実行パスで全機能を提供:
      - ADK SequentialAgent によるパイプライン制御
      - Harness Hook によるガードレール（全ツール呼び出しをラップ）
      - Harness Session による永続化・リジューム
      - Harness Governance による権限チェック + トレース

    Args:
        video_path: RAW動画ファイルパス
        target_minutes: 目標尺（分）
        session_id: セッションID（省略時は自動生成）
        _fallback_model: 429フォールバック時のモデルオーバーライド（内部使用）

    Returns:
        パイプライン実行結果
    """
    from harness.hooks import hook_system, HookEvent, HookInput
    from harness.session_manager import session_manager
    from harness.governance import governance_engine

    sid = session_id or str(uuid.uuid4())
    total_start = time.time()

    # --- Harness セッション作成 ---
    harness_session = session_manager.create_session(video_path=video_path)
    harness_sid = harness_session.session_id

    # --- SessionStart Hook ---
    await hook_system.fire(
        HookEvent.SESSION_START,
        HookInput(
            tool_name="HarnessProductionPipeline",
            session_id=harness_sid,
            metadata={"video_path": video_path, "target_minutes": target_minutes},
        ),
    )

    # --- トレーススパン ---
    trace_span = governance_engine.start_span(
        operation="harness_pipeline",
        tool_name="HarnessProductionPipeline",
    )

    # 例外ブロック内で参照するためスコープ内で定義
    pipeline = None
    fallback_chain = []

    try:
        # 実行中のイベントループを明示的にセットして google.adk 内部の DeprecationWarning を防止
        try:
            loop = asyncio.get_running_loop()
            asyncio.set_event_loop(loop)
        except RuntimeError:
            pass

        from google.adk.runners import InMemoryRunner
        from google.adk.agents.run_config import RunConfig
        from google.genai import types as genai_types

        # フォールバックチェーンを構築
        try:
            from model_registry import get_model as _get_model
            _primary_model = _get_model("supervisor")
        except ImportError:
            _primary_model = "gemini-2.5-flash"

        try:
            from model_governance import model_governance as _mg
            fallback_chain = _mg.build_fallback_sequence(_primary_model)
        except ImportError:
            fallback_chain = [_primary_model]

        # フォールバックモデルが指定されている場合はオーバーライド
        pipeline = build_harness_pipeline(model_override=_fallback_model)
        if _fallback_model:
            logger.info(f"🛡️ Using fallback model: {_fallback_model}")

        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            runner = InMemoryRunner(
                agent=pipeline,
                app_name="antigravity_harness",
            )

        # ADK セッション作成（initial state にパイプラインコンテキストを設定）
        initial_state = {
            "video_path": video_path,
            "target_minutes": target_minutes,
            "harness_session_id": harness_sid,
            "pipeline_started_at": datetime.now().isoformat(),
        }

        await runner.session_service.create_session(
            app_name="antigravity_harness",
            user_id="pipeline_user",
            session_id=sid,
            state=initial_state,
        )

        # --- パイプライン実行 ---
        start_message = (
            f"動画 '{video_path}' の制作パイプラインを開始してください。"
            f"目標尺は{target_minutes}分です。"
        )

        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=start_message)],
        )

        run_config = RunConfig(max_llm_calls=50)

        result_text = await _execute_pipeline_loop(
            runner=runner,
            sid=sid,
            content=content,
            run_config=run_config,
            harness_sid=harness_sid,
        )

        # --- 完了処理 ---
        duration = round(time.time() - total_start, 1)
        governance_engine.end_span(trace_span, status="ok")
        session_manager.complete_session(harness_sid)

        # SessionEnd Hook
        await hook_system.fire(
            HookEvent.SESSION_END,
            HookInput(
                tool_name="HarnessProductionPipeline",
                session_id=harness_sid,
                metadata={"duration_seconds": duration, "status": "success"},
            ),
        )

        logger.info(
            f"✅ HarnessProductionPipeline complete: "
            f"session={harness_sid[:8]}..., duration={duration}s"
        )

        return {
            "status": "success",
            "session_id": sid,
            "harness_session_id": harness_sid,
            "result": result_text,
            "duration_seconds": duration,
        }

    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError, asyncio.TimeoutError) as e:
        return await _handle_pipeline_fallback(
            e=e,
            video_path=video_path,
            target_minutes=target_minutes,
            session_id=session_id,
            _fallback_model=_fallback_model,
            _fallback_attempt=_fallback_attempt,
            _max_fallback_attempts=_max_fallback_attempts,
            fallback_chain=fallback_chain,
            pipeline=pipeline,
            trace_span=trace_span,
            total_start=total_start,
            harness_sid=harness_sid,
            sid=sid,
        )


# ============================================================
# 6. Thumbnail Generation & Quality Validation for Phase 27
# ============================================================

THUMBNAIL_OUTPUT_DIR = Path("backend/temp_thumbnails")

def generate_adk_bridge_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "ADK Bridge Thumbnail"
):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
    from PIL import Image, ImageDraw
    import uuid
    
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 原子的な書き込み (Atomic Write)
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(255, 255, 0))
        img.save(temp_path, "PNG")
        
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except (OSError, ValueError, AttributeError, KeyError) as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        logger.error(f"Failed to generate thumbnail atomically: {e}")
        raise
        
    return output_path

def validate_adk_bridge_thumbnail(file_path) -> dict:
    """サムネイル画像の品質要件（解像度、アスペクト比、ファイルサイズ、破損）を検証する"""
    from PIL import Image, UnidentifiedImageError
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 1. 簡易検証
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError, TypeError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. ピクセルデータのロードによる完全検証
    try:
        with Image.open(file_path) as img:
            img.load()
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError, TypeError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_adk_bridge_thumbnail_task(task_id: str) -> str:
    """StageBoundAgent の process_func として動作する非同期タスク処理"""
    import json
    # 出力先ディレクトリ
    output_path = THUMBNAIL_OUTPUT_DIR / f"{task_id}.png"
    
    # asyncio.to_thread を使用して非同期イベントループのブロッキングを防ぐ
    await asyncio.to_thread(generate_adk_bridge_thumbnail, output_path, text="ADK Bridge Thumbnail")
    result_info = await asyncio.to_thread(validate_adk_bridge_thumbnail, output_path)
    return json.dumps(result_info)

