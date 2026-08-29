"""
pipeline_tools.py — 7つのパイプラインステージをMCP準拠ツールとして登録

Anthropic ACI（Agent-Computer Interface）ベストプラクティスに基づき、
既存 of PipelineStageWorker を ToolRegistry に統合。

設計思想:
  - 各ツールの description は「ジュニアが読んでも使い方明確」レベルで精緻化
  - input_schema で Poka-yoke（パス強制、必須引数チェック）
  - annotations で読み取り専用/破壊的/冪等性を明示
  - ToolRegistry 経由で呼ぶことで、自動的に Hook が発火

Usage:
    from harness.pipeline_tools import register_pipeline_tools
    register_pipeline_tools()  # 全7ツールを tool_registry に登録

    # 実行
    from harness.tool_registry import tool_registry
    result = await tool_registry.execute("transcribe_video", {"video_path": "..."})
"""

import json
import logging
from typing import Dict, Any

from harness.tool_registry import tool_registry

logger = logging.getLogger(__name__)


def _get_or_create_context(args: Dict[str, Any]) -> tuple[Any, Any]:
    from harness.session_manager import session_manager
    from agents.pipeline_types import Segment, PipelineContext

    if not isinstance(args, dict):
        args = {}

    session_id = args.get("session_id")
    video_path = args.get("video_path", "")

    session = None
    if session_id:
        session = session_manager.resume_session(session_id)

    if not session and video_path:
        # video_path をキーに既存アクティブセッションを探す
        for s in session_manager._active_sessions.values():
            if s.video_path == video_path:
                session = s
                break

    if not session:
        session = session_manager.create_session(video_path=video_path, session_id=session_id)

    # セッションから PipelineContext を構築
    ctx = PipelineContext(
        video_path=session.video_path or video_path,
        target_minutes=args.get("target_minutes", 20),
        session_id=session.session_id,
    )

    # セッションの metadata から状態を復元
    meta = session.metadata
    if "segments" in meta:
        ctx.segments = [Segment.from_dict(s) for s in meta["segments"]]
    if "selected_segments" in meta:
        ctx.selected_segments = [Segment.from_dict(s) for s in meta["selected_segments"]]
    if "preview_path" in meta:
        ctx.preview_path = meta["preview_path"]
    if "final_path" in meta:
        ctx.final_path = meta["final_path"]
    if "quality_score" in meta:
        ctx.quality_score = meta["quality_score"]
    # **値と旗は一緒に運ぶ**（R1.5-C4・10周目 N-3）。点だけ戻すと、
    # 採点済みの実走が再開後に「未計測」に化ける
    ctx.quality_scored = bool(meta.get("quality_scored", False))
    if "metadata" in meta:
        ctx.metadata = meta["metadata"]

    # 引数 args に明示的に渡された値があれば上書き
    if "segments" in args and args["segments"] is not None:
        ctx.segments = []
        segments_arg = args["segments"]
        if isinstance(segments_arg, list):
            for s in segments_arg:
                if isinstance(s, dict):
                    ctx.segments.append(Segment.from_dict(s))
                elif isinstance(s, Segment):
                    ctx.segments.append(s)
    if "selected_segments" in args and args["selected_segments"] is not None:
        ctx.selected_segments = []
        sel_segments_arg = args["selected_segments"]
        if isinstance(sel_segments_arg, list):
            for s in sel_segments_arg:
                if isinstance(s, dict):
                    ctx.selected_segments.append(Segment.from_dict(s))
                elif isinstance(s, Segment):
                    ctx.selected_segments.append(s)
    if "preview_path" in args and args["preview_path"] is not None:
        ctx.preview_path = args["preview_path"]
    if "metadata" in args and args["metadata"] is not None:
        metadata_arg = args["metadata"]
        if isinstance(metadata_arg, dict):
            ctx.metadata.update(metadata_arg)

    return ctx, session


def _save_context(ctx: Any, session: Any) -> None:
    from harness.session_manager import session_manager

    def serialize_segment(s):
        if isinstance(s, dict):
            return s
        elif hasattr(s, "to_dict"):
            return s.to_dict()
        return s

    # コンテキストの状態をセッションの metadata に保存
    session.metadata["segments"] = [serialize_segment(s) for s in ctx.segments]
    session.metadata["selected_segments"] = [serialize_segment(s) for s in ctx.selected_segments]
    session.metadata["preview_path"] = ctx.preview_path
    session.metadata["final_path"] = ctx.final_path
    session.metadata["quality_score"] = ctx.quality_score
    session.metadata["quality_scored"] = getattr(ctx, "quality_scored", False)
    session.metadata["metadata"] = ctx.metadata

    session_manager._save_session(session)


# ============================================================
# 0. 文字起こし（Whisper サブプロセス）
# ============================================================
async def transcribe_video_tool(args: Dict) -> Dict:
    from agents.pipeline_coordinator import TranscribeWorker

    try:
        ctx, session = _get_or_create_context(args)
        worker = TranscribeWorker()
        result = await worker.execute(ctx)

        if result.success:
            _save_context(ctx, session)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "success": result.success,
                    "detail": result.detail,
                    "segment_count": result.data.get("segment_count", 0),
                    "duration_seconds": result.duration_seconds,
                    "segments": [s.to_dict() if hasattr(s, "to_dict") else s for s in ctx.segments[:5]] if ctx.segments else [],
                    "total_segments": len(ctx.segments),
                }, ensure_ascii=False),
            }],
            "is_error": not result.success,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in transcribe_video_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


# ============================================================
# 1. AI校閲（辞書 + Gemini）
# ============================================================
async def proofread_subtitles_tool(args: Dict) -> Dict:
    from agents.pipeline_coordinator import ProofreadWorker

    try:
        ctx, session = _get_or_create_context(args)
        worker = ProofreadWorker()
        result = await worker.execute(ctx)

        if result.success:
            _save_context(ctx, session)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "success": result.success,
                    "detail": result.detail,
                    "corrections": result.data,
                    "duration_seconds": result.duration_seconds,
                }, ensure_ascii=False),
            }],
            "is_error": not result.success,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in proofread_subtitles_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


# ============================================================
# 2. SmartCut 構成提案
# ============================================================
async def propose_smart_cut_tool(args: Dict) -> Dict:
    from agents.pipeline_coordinator import SmartCutWorker

    try:
        ctx, session = _get_or_create_context(args)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        if result.success:
            _save_context(ctx, session)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "success": result.success,
                    "detail": result.detail,
                    "selected_count": len(ctx.selected_segments),
                    "data": result.data,
                    "duration_seconds": result.duration_seconds,
                }, ensure_ascii=False),
            }],
            "is_error": not result.success,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in propose_smart_cut_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


# ============================================================
# 3. プレビュー生成（FFmpeg）
# ============================================================
async def generate_preview_tool(args: Dict) -> Dict:
    from agents.pipeline_coordinator import PreviewWorker

    try:
        ctx, session = _get_or_create_context(args)
        worker = PreviewWorker()
        result = await worker.execute(ctx)

        if result.success:
            _save_context(ctx, session)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "success": result.success,
                    "detail": result.detail,
                    "preview_path": ctx.preview_path,
                    "data": result.data,
                    "duration_seconds": result.duration_seconds,
                }, ensure_ascii=False),
            }],
            "is_error": not result.success,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in generate_preview_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


# ============================================================
# 4. YouTube最適化メタデータ生成
# ============================================================
async def optimize_youtube_tool(args: Dict) -> Dict:
    from agents.pipeline_coordinator import YouTubeOptWorker

    try:
        ctx, session = _get_or_create_context(args)
        worker = YouTubeOptWorker()
        result = await worker.execute(ctx)

        if result.success:
            _save_context(ctx, session)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "success": result.success,
                    "detail": result.detail,
                    "metadata": ctx.metadata,
                    "duration_seconds": result.duration_seconds,
                }, ensure_ascii=False),
            }],
            "is_error": not result.success,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in optimize_youtube_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


# ============================================================
# 5. 品質チェック
# ============================================================
async def check_quality_tool(args: Dict) -> Dict:
    from agents.pipeline_coordinator import QualityGateWorker

    try:
        ctx, session = _get_or_create_context(args)
        worker = QualityGateWorker()
        result = await worker.execute(ctx)

        if result.success:
            _save_context(ctx, session)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "success": result.success,
                    "detail": result.detail,
                    "score": result.data.get("score", 0),
                    "rank": result.data.get("rank", "C"),
                    "feedback": result.data.get("feedback", []),
                    "category_scores": result.data.get("category_scores", {}),
                    "duration_seconds": result.duration_seconds,
                }, ensure_ascii=False),
            }],
            "is_error": not result.success,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in check_quality_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


# ============================================================
# 6. 最終レンダリング
# ============================================================
async def render_final_tool(args: Dict) -> Dict:
    from agents.pipeline_coordinator import RenderWorker

    try:
        ctx, session = _get_or_create_context(args)
        worker = RenderWorker()
        result = await worker.execute(ctx)

        if result.success:
            _save_context(ctx, session)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "success": result.success,
                    "detail": result.detail,
                    "final_path": ctx.final_path,
                    "data": result.data,
                    "duration_seconds": result.duration_seconds,
                }, ensure_ascii=False),
            }],
            "is_error": not result.success,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in render_final_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


# ============================================================
# 8. ディスククリーンアップ（ハーネス管轄下の破壊的操作）
# ============================================================
async def cleanup_intermediates_tool(args: dict) -> dict:
    from disk_manager import cleanup_intermediates as _cleanup, get_free_gb

    try:
        keep = args.get("keep_latest", 1) if isinstance(args, dict) else 1
        dry = args.get("dry_run", False) if isinstance(args, dict) else False
        freed_gb = _cleanup(keep_latest=keep, dry_run=dry)
        free_gb = get_free_gb()

        action = "削除予定" if dry else "削除済み"
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "action": action,
                    "freed_gb": round(freed_gb, 2),
                    "free_gb": round(free_gb, 2),
                }, ensure_ascii=False),
            }],
            "is_error": False,
        }
    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Error in cleanup_intermediates_tool: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {type(e).__name__} - {e}"}],
            "is_error": True,
        }


def register_pipeline_tools() -> None:
    """
    全7ステージのパイプラインツールを ToolRegistry に登録。

    既存の PipelineStageWorker の execute() を薄くラップし、
    MCP content 形式で結果を返す。
    """

    tool_registry.register(
        name="transcribe_video",
        description=(
            "動画ファイルを Whisper で文字起こしし、タイムスタンプ付き字幕データを返す。\n"
            "処理時間: 30分動画で約2-5分（GPU依存）。\n"
            "出力: セグメント配列 [{start, end, text}, ...]。\n"
            "チェックポイントファイルが既存の場合はWhisperをスキップしキャッシュを使用する。"
        ),
        input_schema={
            "video_path": str,
            "target_minutes": {"type": int, "default": 20},
            "session_id": {"type": str, "default": ""},
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        required_scopes={"transcriber"},
    )(transcribe_video_tool)

    tool_registry.register(
        name="proofread_subtitles",
        description=(
            "字幕セグメントを校閲する。2段階: \n"
            "  1) 固有名詞辞書による自動修正\n"
            "  2) Gemini API によるAI校閲（文脈依存の誤り修正）\n"
            "入力: segments 配列。出力: 修正件数と修正後セグメント。"
        ),
        input_schema={
            "video_path": str,
            "segments": {"type": list, "default": None},
            "session_id": {"type": str, "default": ""},
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        required_scopes={"proofreader"},
    )(proofread_subtitles_tool)

    tool_registry.register(
        name="propose_smart_cut",
        description=(
            "字幕セグメントを分析し、目標尺に収まる構成案を提案する。\n"
            "Gemini API で重要度を判定し、優先度の高いセグメントを選定。\n"
            "入力: segments, video_path, target_minutes。\n"
            "出力: 選定されたセグメント配列と推定尺。"
        ),
        input_schema={
            "video_path": str,
            "segments": {"type": list, "default": None},
            "target_minutes": {"type": int, "default": 20},
            "session_id": {"type": str, "default": ""},
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    )(propose_smart_cut_tool)

    tool_registry.register(
        name="generate_preview",
        description=(
            "選定されたセグメントから FFmpeg でプレビュー動画を生成する。\n"
            "入力: video_path, selected_segments。\n"
            "出力: プレビューファイルパスとサイズ（MB）。\n"
            "⚠️ ディスク容量が必要（動画サイズ依存）。"
        ),
        input_schema={
            "video_path": str,
            "selected_segments": {"type": list, "default": None},
            "session_id": {"type": str, "default": ""},
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
        required_scopes={"renderer"},
    )(generate_preview_tool)

    tool_registry.register(
        name="optimize_youtube",
        description=(
            "字幕テキストからYouTube用メタデータを生成する。\n"
            "生成内容: タイトル案、説明文、タグ、チャプターマーカー。\n"
            "Gemini API 利用可能時は AI 生成、不可時はキーワード抽出で簡易生成。"
        ),
        input_schema={
            "video_path": str,
            "segments": {"type": list, "default": None},
            "session_id": {"type": str, "default": ""},
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        required_scopes={"optimizer"},
    )(optimize_youtube_tool)

    tool_registry.register(
        name="check_quality",
        description=(
            "プレビュー動画の品質を多角的にチェックし、100点満点でスコアリングする。\n"
            "チェック項目: ファイル整合性、音声レベル、字幕精度、構成バランス等。\n"
            "90点以上で合格（ランクA以上）。\n"
            "出力: score, rank(S/A/B/C), feedback(改善提案配列)。"
        ),
        input_schema={
            "video_path": str,
            "preview_path": str,
            "segments": {"type": list, "default": None},
            "selected_segments": {"type": list, "default": None},
            "metadata": {"type": dict, "default": {}},
            "session_id": {"type": str, "default": ""},
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        required_scopes={"quality_gate"},
    )(check_quality_tool)

    tool_registry.register(
        name="render_final",
        description=(
            "プレビュー動画を本番品質で最終レンダリングする。\n"
            "処理: GPU/CPU対応の高品質エンコード + 音声ラウドネス正規化（-16 LUFS）。\n"
            "⚠️ 破壊的操作: 出力ディレクトリにファイルを書き込む。\n"
            "⚠️ 長時間処理: 30分動画で5-15分。"
        ),
        input_schema={
            "video_path": str,
            "preview_path": str,
            "session_id": {"type": str, "default": ""},
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
        },
        required_scopes={"renderer"},
    )(render_final_tool)

    tool_registry.register(
        name="cleanup_intermediates",
        description=(
            "中間ファイル（merged, preview, SmartCut一時ファイル）を削除してディスク容量を確保する。\n"
            "final/ の成果物は保護される（削除されない）。\n"
            "keep_latest: 各ディレクトリで保持する最新ファイル数（デフォルト1）。\n"
            "dry_run: trueなら削除せずログのみ出力。"
        ),
        input_schema={
            "keep_latest": {"type": int, "default": 1, "description": "保持する最新ファイル数"},
            "dry_run": {"type": bool, "default": False, "description": "trueなら削除せずログのみ"},
        },
        annotations={"destructiveHint": True, "idempotentHint": True, "readOnlyHint": False},
    )(cleanup_intermediates_tool)

    tool_count = len(tool_registry.list_tools())
    logger.info(f"🔧 パイプラインツール登録完了: {tool_count} tools in registry")
