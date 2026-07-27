"""
GovernanceEngine — スコープ付き権限管理・実行トレース

Anthropic推奨のガバナンスパターンを実装:
  - スコープ付き権限: 各エージェント/サブタスクが使えるツールを厳密に制限
  - 実行トレース: 全ツール呼び出しを OpenTelemetry 互換の構造化トレースで記録
  - コスト監視: 既存 usage_tracker との統合

設計思想:
  - Claude Agent SDK の permissions / tools リスト / cost-tracking 概念準拠
  - 最小権限の原則: 各エージェントに必要最小限のツールのみ付与
  - Defense in Depth: 複数レイヤーでの防御

Claude Agent SDK 原文:
  "Configure permissions to control what tools agents can use.
   Each subagent's tools array restricts what it can access."
"""

import json
import logging
import time
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# トレースログの保存先
TRACE_DIR = Path(__file__).parent.parent / "data" / "traces"


# ============================================================
# データ構造
# ============================================================

@dataclass
class AgentScope:
    """
    エージェントの権限スコープ定義。

    Claude Agent SDK の AgentDefinition.tools に相当。
    各エージェント/サブタスクが使用可能なツールと操作権限を定義。
    """
    agent_id: str
    agent_name: str
    description: str
    # 使用可能なツール（ホワイトリスト方式）
    allowed_tools: Set[str] = field(default_factory=set)
    # 禁止ツール（ブラックリスト、allowed_tools が空の場合に使用）
    disallowed_tools: Set[str] = field(default_factory=set)
    # 操作権限
    can_read: bool = True
    can_write: bool = False
    can_execute: bool = False  # サブプロセス実行
    can_network: bool = False  # 外部API呼び出し
    # 制限
    max_retries: int = 3
    timeout_seconds: int = 600
    # コスト上限（API呼び出し回数）
    max_api_calls: int = 100
    current_api_calls: int = 0
    # コスト上限（トークン数）
    max_tokens: int = 1000000
    current_tokens: int = 0


@dataclass
class TraceSpan:
    """実行トレースのスパン（OpenTelemetry 互換）"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation: str
    tool_name: str
    start_time: str
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str = "ok"  # ok, error
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """スパン情報をシリアライズ可能な辞書形式に変換します。"""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "tool_name": self.tool_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


# ============================================================
# 定義済みスコープ（パイプライン用）
# ============================================================

PIPELINE_SCOPES: Dict[str, AgentScope] = {
    "transcriber": AgentScope(
        agent_id="transcriber",
        agent_name="文字起こしエージェント",
        description="Whisper による音声認識と字幕データ生成",
        allowed_tools={"transcribe_video"},
        can_read=True,
        can_write=False,
        can_execute=True,   # Whisper サブプロセス
        can_network=False,
        timeout_seconds=900,  # 15分（長尺動画対応）
    ),
    "proofreader": AgentScope(
        agent_id="proofreader",
        agent_name="AI校閲エージェント",
        description="固有名詞辞書と Gemini API による字幕校閲",
        allowed_tools={"proofread_subtitles"},
        can_read=True,
        can_write=False,
        can_execute=False,
        can_network=True,  # Gemini API
        max_api_calls=50,
    ),
    "quality_gate": AgentScope(
        agent_id="quality_gate",
        agent_name="品質管理エージェント",
        description="品質スコア評価とプレビュー確認",
        allowed_tools={"check_quality", "generate_preview"},
        can_read=True,
        can_write=False,
        can_execute=False,
        can_network=True,  # 品質評価API
    ),
    "renderer": AgentScope(
        agent_id="renderer",
        agent_name="レンダリングエージェント",
        description="FFmpeg による最終レンダリングおよびプレビュー生成",
        allowed_tools={"render_final", "generate_preview"},
        can_read=True,
        can_write=True,     # 出力ファイル生成
        can_execute=True,   # FFmpeg
        can_network=False,
        timeout_seconds=1200,  # 20分
    ),
    "optimizer": AgentScope(
        agent_id="optimizer",
        agent_name="YouTube最適化エージェント",
        description="メタデータ生成とアップロード準備",
        allowed_tools={"optimize_youtube"},
        can_read=True,
        can_write=True,
        can_execute=False,
        can_network=True,   # YouTube API
    ),
    "smartcut": AgentScope(
        agent_id="smartcut",
        agent_name="SmartCutエージェント",
        description="AIベースの自動カット編集構成",
        allowed_tools={"configure_smartcut", "propose_smart_cut"},
        can_read=True,
        can_write=False,
        can_execute=False,
        can_network=True,   # Gemini API (SmartCut分析)
        max_api_calls=30,
    ),
}


# ============================================================
# GovernanceEngine
# ============================================================

class GovernanceEngine:
    """
    ガバナンスエンジン。

    3つの柱:
    1. 権限管理: AgentScope によるツールアクセス制御
    2. 実行トレース: OpenTelemetry 互換の構造化ログ
    3. コスト監視: API呼び出し回数の追跡と制限

    Usage:
        from harness.governance import governance_engine

        # 権限チェック
        can_use = governance_engine.check_permission("transcriber", "transcribe_video")

        # トレース開始/終了
        span_id = governance_engine.start_span("transcribe", "transcribe_video")
        governance_engine.end_span(span_id, status="ok")
    """

    def __init__(self, trace_dir: Optional[Path] = None):
        self._scopes: Dict[str, AgentScope] = dict(PIPELINE_SCOPES)
        self._trace_dir = trace_dir or TRACE_DIR
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._active_spans: Dict[str, TraceSpan] = {}
        self._completed_spans: List[TraceSpan] = []
        self._span_sequence_id = 0

    # ============================================================
    # 権限管理
    # ============================================================

    def check_permission(
        self,
        agent_id: str,
        tool_name: str,
    ) -> bool:
        """
        ツール使用権限をチェック。

        最小権限の原則:
        - allowed_tools が定義されていれば、ホワイトリスト方式
        - disallowed_tools が定義されていれば、ブラックリスト方式
        - どちらもなければ許可
        """
        scope = self._scopes.get(agent_id)
        if not scope:
            return True  # スコープ未定義 = 制限なし

        # ホワイトリスト方式
        if scope.allowed_tools:
            return self._check_whitelist(scope, tool_name)

        # ブラックリスト方式
        if scope.disallowed_tools:
            return self._check_blacklist(scope, tool_name)

        return True

    def _check_whitelist(self, scope: AgentScope, tool_name: str) -> bool:
        """ホワイトリスト方式による使用権限のチェックを行います。"""
        allowed = tool_name in scope.allowed_tools
        if not allowed:
            logger.warning(
                f"🚫 Permission denied: {scope.agent_id} → {tool_name} "
                f"(allowed: {scope.allowed_tools})"
            )
        return allowed

    def _check_blacklist(self, scope: AgentScope, tool_name: str) -> bool:
        """ブラックリスト方式による使用権限のチェックを行います。"""
        denied = tool_name in scope.disallowed_tools
        if denied:
            logger.warning(
                f"🚫 Permission denied: {scope.agent_id} → {tool_name} (blacklisted)"
            )
        return not denied

    def check_rate_limit(self, agent_id: str) -> bool:
        """API呼び出し回数の制限チェック"""
        scope = self._scopes.get(agent_id)
        if not scope:
            return True

        if scope.current_api_calls >= scope.max_api_calls:
            logger.warning(
                f"🚫 Rate limit: {agent_id} "
                f"({scope.current_api_calls}/{scope.max_api_calls})"
            )
            return False

        scope.current_api_calls += 1
        return True

    def check_token_limit(self, agent_id: str, tokens: int) -> bool:
        """指定されたトークン数を消費可能かチェックし、可能であれば消費量を累積します。"""
        scope = self._scopes.get(agent_id)
        if not scope:
            return True

        if scope.current_tokens + tokens > scope.max_tokens:
            logger.warning(
                f"🚫 Token limit exceeded for {agent_id}: "
                f"requested {tokens}, current {scope.current_tokens}/{scope.max_tokens}"
            )
            return False

        scope.current_tokens += tokens
        return True

    def register_scope(self, scope: AgentScope) -> None:
        """カスタムスコープを登録"""
        self._scopes[scope.agent_id] = scope
        logger.info(f"🔒 Scope registered: {scope.agent_id}")

    # ============================================================
    # 実行トレース（OpenTelemetry 互換）
    # ============================================================

    def _generate_span_id(self) -> str:
        """ユニークなスパンIDを生成します。"""
        self._span_sequence_id += 1
        return f"span-{self._span_sequence_id:06d}"

    def _resolve_trace_id(self, trace_id: Optional[str]) -> str:
        """トレースIDを解決します（指定がない場合は新規生成）。"""
        return trace_id or f"trace-{int(time.time())}"

    def start_span(
        self,
        operation: str,
        tool_name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict] = None,
    ) -> str:
        """
        トレーススパンを開始。

        Returns:
            span_id
        """
        span_id = self._generate_span_id()
        actual_trace_id = self._resolve_trace_id(trace_id)

        span = TraceSpan(
            trace_id=actual_trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation=operation,
            tool_name=tool_name,
            start_time=datetime.now().isoformat(),
            attributes=attributes or {},
        )

        self._active_spans[span_id] = span
        return span_id

    def _calculate_duration_ms(self, start_time: str, end_time: str) -> float:
        """ISOフォーマットの開始・終了時刻文字列から経過ミリ秒数を計算"""
        try:
            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(end_time)
            return (end - start).total_seconds() * 1000
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to calculate span duration: {e}")
            return 0.0

    def _update_span_attributes(self, span: TraceSpan, attributes: Optional[Dict]) -> None:
        """スパンの属性を更新します（例外をキャッチしてログ出力）"""
        if not attributes:
            return
        try:
            span.attributes.update(attributes)
        except (AttributeError, TypeError, ValueError) as e:
            logger.error(f"Failed to update span attributes: {e}")

    def _log_completed_span(self, span: TraceSpan) -> None:
        """完了したスパンの情報をログ出力します"""
        duration_val = span.duration_ms if span.duration_ms is not None else 0.0
        logger.info(
            f"📊 Span: {span.operation}/{span.tool_name} "
            f"[{span.status}] {duration_val:.0f}ms"
        )

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        attributes: Optional[Dict] = None,
    ) -> None:
        """トレーススパンを終了"""
        span = self._active_spans.pop(span_id, None)
        if not span:
            return

        span.end_time = datetime.now().isoformat()
        span.status = status
        self._update_span_attributes(span, attributes)

        # duration 計算
        span.duration_ms = self._calculate_duration_ms(span.start_time, span.end_time)

        self._completed_spans.append(span)

        # ログ出力
        self._log_completed_span(span)

    def add_span_event(
        self, span_id: str, name: str, attributes: Optional[Dict] = None,
    ) -> None:
        """スパンにイベントを追加"""
        span = self._active_spans.get(span_id)
        if span:
            span.events.append({
                "name": name,
                "timestamp": datetime.now().isoformat(),
                "attributes": attributes or {},
            })

    # ============================================================
    # トレースの永続化・取得
    # ============================================================

    def _sanitize_session_id(self, session_id: Optional[str]) -> str:
        """session_id のディレクトリトラバーサル対策（サニタイズ）"""
        if not session_id:
            return 'default'
        safe_session_id = Path(session_id).name
        if not safe_session_id or safe_session_id in ('.', '..'):
            return 'default'
        return safe_session_id

    def _generate_trace_filepath(self, session_id: Optional[str]) -> Path:
        """セッションIDに基づいたトレースログのファイルパスを生成します"""
        safe_session_id = self._sanitize_session_id(session_id)
        filename = f"trace_{safe_session_id}_{int(time.time())}.jsonl"
        return self._trace_dir / filename

    def _save_spans_to_file(self, filepath: Path) -> None:
        """完了したスパンをJSONL形式で指定されたパスに書き出します"""
        with open(filepath, "w", encoding="utf-8") as f:
            for span in self._completed_spans:
                line = json.dumps(span.to_dict(), ensure_ascii=False)
                f.write(line + "\n")

    def flush_traces(self, session_id: Optional[str] = None) -> None:
        """完了したスパンをディスクに書き出し"""
        if not self._completed_spans:
            return

        trace_path = self._generate_trace_filepath(session_id)

        try:
            self._save_spans_to_file(trace_path)

            logger.info(
                f"📊 Traces flushed: {len(self._completed_spans)} spans → {trace_path.name}"
            )
            self._completed_spans.clear()

        except (OSError, ValueError, TypeError) as e:
            logger.error(f"Trace flush failed: {e}")

    def get_recent_traces(self, limit: int = 50) -> List[Dict]:
        """直近のトレーススパン"""
        return [
            {
                "span_id": s.span_id,
                "operation": s.operation,
                "tool_name": s.tool_name,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "start_time": s.start_time,
            }
            for s in self._completed_spans[-limit:]
        ]

    def get_trace_tree(self, trace_id: str) -> list:
        """特定の trace_id に属する完了スパンを親子関係に基づいて階層的ツリー構造として構築します。"""
        spans = self._filter_spans_by_trace(trace_id)
        if not spans:
            return []

        nodes = self._build_nodes_dict(spans)
        return self._assemble_tree(spans, nodes)

    def _filter_spans_by_trace(self, trace_id: str) -> List[TraceSpan]:
        """指定された trace_id に一致する完了スパンを抽出します。"""
        return [s for s in self._completed_spans if s.trace_id == trace_id]

    def _build_nodes_dict(self, spans: List[TraceSpan]) -> Dict[str, Dict[str, Any]]:
        """スパンのリストから、親子構造構築用のノード辞書を生成します。"""
        nodes = {}
        for s in spans:
            nodes[s.span_id] = {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "operation": s.operation,
                "tool_name": s.tool_name,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "attributes": s.attributes,
                "events": s.events,
                "children": []
            }
        return nodes

    def _assemble_tree(self, spans: List[TraceSpan], nodes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """ノード親子関係を紐づけ、ルートノードのツリーリストを組み立てます。"""
        roots = []
        for s in spans:
            node = nodes[s.span_id]
            if s.parent_span_id and s.parent_span_id in nodes:
                nodes[s.parent_span_id]["children"].append(node)
            else:
                roots.append(node)
        return roots

    # ============================================================
    # 統計
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """ガバナンス統計"""
        scope_stats = {}
        for agent_id, scope in self._scopes.items():
            scope_stats[agent_id] = {
                "name": scope.agent_name,
                "allowed_tools": list(scope.allowed_tools),
                "api_calls": f"{scope.current_api_calls}/{scope.max_api_calls}",
                "tokens": f"{scope.current_tokens}/{scope.max_tokens}",
            }

        return {
            "scopes": scope_stats,
            "active_spans": len(self._active_spans),
            "completed_spans": len(self._completed_spans),
            "total_span_count": self._span_sequence_id,
        }

    def reset_api_counters(self) -> None:
        """API呼び出しとトークンカウンターをリセット（日次リセット用）"""
        for scope in self._scopes.values():
            scope.current_api_calls = 0
            scope.current_tokens = 0
        logger.info("🔄 API and token counters reset")

    def _validate_no_failed_tasks(self, failed: int) -> None:
        """失敗したタスク数を検証し、エラーがあれば例外を送出します。"""
        if failed > 0:
            logger.error(
                f"🛑 [Quality Gate Blocked] {failed} tasks failed in batch. "
                f"Halting report submission to prevent regression."
            )
            raise ValueError(
                f"🚫 [Quality Gate Blocked] 失敗したタスクが {failed} 件存在します。"
                f"デグレード（退行）防止のため、バッチ報告の提出をブロックします。"
            )

    def _is_production_file(self, file_path: str) -> bool:
        """指定された相対ファイルパスが本番コードであるかを判定（除外パターンと照合）"""
        file_path_normalized = file_path.replace("\\", "/")

        # テスト関連ファイル
        if "tests/" in file_path_normalized or "/test_" in file_path_normalized or file_path_normalized.startswith("test_"):
            return False
        # アーティファクト
        if "Human01_Official Artifact/" in file_path_normalized:
            return False
        # 一時スクリプト・スクラッチ
        if file_path_normalized.startswith("scratch/") or "/scratch/" in file_path_normalized:
            return False
        if "temp_thumbnails" in file_path_normalized:
            return False
        # ドキュメント・データ
        if file_path_normalized.endswith((".md", ".txt", ".json", ".jsonl")):
            return False
        # 自動生成された一時ランナースクリプト
        if any(pattern in file_path_normalized for pattern in ("flash_assign_subagents", "flash_runner", "mark_tasks")):
            return False

        return True

    def _run_git_command(self, args: List[str]) -> subprocess.CompletedProcess:
        """Gitコマンドを実行し、結果オブジェクトを返します。"""
        return subprocess.run(
            args,
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace"
        )

    def _get_git_changed_files(self) -> List[str]:
        """Git から変更された（追跡中・未追跡の）ファイル名一覧を取得します。"""
        # 追跡中の変更ファイル名
        diff_process = self._run_git_command(["git", "diff", "--name-only"])
        # 未追跡 of 新規ファイル名
        untracked_process = self._run_git_command(["git", "ls-files", "--others", "--exclude-standard"])
        return [f.strip() for f in (diff_process.stdout + "\n" + untracked_process.stdout).split("\n") if f.strip()]

    def _fetch_git_changes(self) -> List[str]:
        """Gitコマンドを使用して、変更されたファイルと未追跡のファイルの一覧を取得します。"""
        try:
            return self._get_git_changed_files()
        except Exception as e:
            logger.warning(f"Failed to fetch git changes via command: {e}")
            return []

    def _count_production_file_changes(self, report: Dict[str, Any]) -> int:
        """
        git diff から変更された本番コードファイル数を取得します。
        
        エラー発生時は、レポート内の git_diff_summary からフォールバック取得します。
        """
        try:
            all_files = self._fetch_git_changes()
            if not all_files:
                # コマンド実行失敗等の場合はフォールバック
                git_diff = report.get("git_diff_summary", {})
                return git_diff.get("files_changed", 0)

            production_changes = [
                f for f in all_files
                if self._is_production_file(f)
            ]
            files_changed = len(production_changes)
            logger.info(
                f"📊 [Quality Gate] Files modified (raw: {len(all_files)}, production: {files_changed})"
            )
            return files_changed
        except Exception as e:
            logger.warning(f"Failed to calculate production git diff: {e}")
            # フォールバック
            git_diff = report.get("git_diff_summary", {})
            return git_diff.get("files_changed", 0)

    def _validate_production_files_limit(self, files_changed: int, tasks_count: int) -> None:
        """変更された本番ファイル数が制限を超えているか検証し、超えている場合は例外を送出します。"""
        # 1タスクあたり最大3ファイル制限。タスク数が0の場合は最低3ファイルまで許容。
        max_allowed_files = max(3, tasks_count * 3)
        if files_changed > max_allowed_files:
            logger.error(
                f"🛑 [Quality Gate Blocked] Production files changed ({files_changed}) exceeds limit ({max_allowed_files}) "
                f"for {tasks_count} tasks."
            )
            raise ValueError(
                f"🚫 [Quality Gate Blocked] 変更された本番ファイル数が制限値（{files_changed} > 上限 {max_allowed_files}）を超えています。"
                f"1タスクあたり最大3ファイルまでの変更に抑えてください。"
            )

    def validate_batch_quality(
        self,
        results: Dict[str, Any],
        report: Dict[str, Any],
    ) -> None:
        """
        バッチの品質検証を実行（Stage 2 品質ゲート統合）。
        基準を満たさない場合、ValueError をスローしてバッチ処理をハードストップさせます。
        
        検証項目:
        1. 失敗タスクチェック: results["failed"] > 0 の場合は即ブロック（退行防止）
        2. 変更ファイル数制限: 1タスクあたり最大3ファイル上限（または最低3ファイル）を超える場合はブロック
        """
        passed_count = results.get("passed", 0)
        failed_count = results.get("failed", 0)
        total_count = results.get("total", 0)

        # 1. 退行防止: 失敗したタスクチェック
        self._validate_no_failed_tasks(failed_count)

        # 2. 変更ファイル数の検証
        files_changed = self._count_production_file_changes(report)

        tasks_list = report.get("tasks", [])
        tasks_count = len(tasks_list)

        self._validate_production_files_limit(files_changed, tasks_count)

        logger.info(
            f"🟢 [Quality Gate Passed] Batch validation successful (passed: {passed_count}, total: {total_count}, production files: {files_changed})"
        )


# ============================================================
# シングルトン
# ============================================================
governance_engine = GovernanceEngine()
