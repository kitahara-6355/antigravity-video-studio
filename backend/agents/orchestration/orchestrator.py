"""
Orchestration Hub — Flash/Opus 自律連携 of 共通処理機構

プロジェクト2 (Gemini 3.5 Flash) とプロジェクト3 (Claude Opus 4.6) が
ファイルシステム上の共有データを介して自律的に連携するためのAPI。

使用方法:
    from backend.agents.orchestration import OrchestrationHub
    hub = OrchestrationHub()
    batch = hub.get_next_batch(phase=5, milestone="M5.1")
"""

import json
import logging
from pathlib import Path
from .hub_session import SessionMixin
from .hub_status import StatusMixin
from .hub_batch import BatchMixin
from .hub_gate import GateMixin
from .hub_reports import ReportsMixin
from .hub_common import (
    TASK_QUEUE_PATH, OPUS_DIRECTIVE_PATH, FLASH_REPORTS_PATH,
    MESSAGE_BOX_PATH, FLASH_SESSION_PATH, PHASE_GATES_PATH,
    PHASE_STATE_PATH, INBOX_DIR, _PROJECT_ROOT,
    _write_json,
    _safe_parse_iso,
    _read_json,
    _append_jsonl,
    _read_jsonl,
    _now_iso,
    _rotate_jsonl_if_needed,
    OpusQuotaExceededException
)

from .generator import TaskGenerator
from .verifier import CodeVerifier
from .dynamic_decomposer import DynamicDecomposer

logger = logging.getLogger(__name__)


class OrchestrationHub(SessionMixin, StatusMixin, BatchMixin, GateMixin, ReportsMixin):
    """
    Flash/Opus 自律連携の共通処理機構。
    
    Mixin クラス群 (hub_session, hub_status, hub_batch, hub_gate, hub_reports) を
    多重継承し、すべての公開 API・戻り値型・挙動において完全な下位互換性を維持する。
    """

    def __init__(self):
        self._ensure_files_exist()
        self._instrument_fail_counts: dict[str, int] = {}  # 自動計装の連続失敗カウンタ

    def _ensure_files_exist(self) -> None:
        """必要なファイルが存在しない場合、初期化する"""
        if not TASK_QUEUE_PATH.exists():
            _write_json(TASK_QUEUE_PATH, self._empty_queue())
        if not OPUS_DIRECTIVE_PATH.exists():
            _write_json(OPUS_DIRECTIVE_PATH, self._empty_directive())
        if not FLASH_REPORTS_PATH.exists():
            FLASH_REPORTS_PATH.touch()
        if not MESSAGE_BOX_PATH.exists():
            MESSAGE_BOX_PATH.touch()
        if not FLASH_SESSION_PATH.exists():
            _write_json(FLASH_SESSION_PATH, {
                "session_started_at": None, "session_ended_at": None,
                "exit_reason": None, "last_heartbeat": None,
                "status": "not_started", "batches_in_session": 0,
            })
        # Phase gates の初期定義（ゲート未定義でのPhase自動進行防止）
        if not PHASE_GATES_PATH.exists():
            _write_json(PHASE_GATES_PATH, {
                "5":  {"min_coverage": 35, "max_critical_debt": 10},
                "6":  {"min_coverage": 45, "max_critical_debt": 5},
                "7":  {"min_coverage": 55, "max_critical_debt": 3},
                "8":  {"min_coverage": 60, "max_critical_debt": 2},
                "9":  {"min_coverage": 65, "max_critical_debt": 1},
                "10": {"min_coverage": 70, "max_critical_debt": 0},
                "11": {"min_coverage": 72, "max_critical_debt": 0},
                "12": {"min_coverage": 75, "max_critical_debt": 0},
                "13": {"min_coverage": 77, "max_critical_debt": 0},
                "14": {"min_coverage": 80, "max_critical_debt": 0},
                "15": {"min_coverage": 82, "max_critical_debt": 0},
                "16": {"min_coverage": 83, "max_critical_debt": 0},
                "17": {"min_coverage": 85, "max_critical_debt": 0},
                "18": {"min_coverage": 85, "max_critical_debt": 0},
                "19": {"min_coverage": 85, "max_critical_debt": 0},
                "20": {"min_coverage": 85, "max_critical_debt": 0},
            })

    def verify_file(self, file_path: str) -> dict:
        """検証対象のファイルを静的/動的にチェックする"""
        # 入力ガードレール：不正なパスのチェック
        import os
        path_obj = Path(file_path)
        is_invalid = (
            path_obj.is_absolute()
            or os.path.isabs(file_path)
            or file_path.startswith("/")
            or file_path.startswith("\\")
            or ".." in path_obj.parts
        )
        if is_invalid:
            return {"passed": False, "error": "Invalid file path: path must be relative and within workspace"}
        
        # 入力ガードレール：ファイルサイズ制限（1MB以下）のチェック
        abs_path = _PROJECT_ROOT / path_obj
        if abs_path.exists():
            if abs_path.stat().st_size > 1024 * 1024:  # 1MB
                return {"passed": False, "error": "File size exceeds 1MB limit"}

        verifier = CodeVerifier()
        return verifier.verify_static(file_path)

    def verify_test_suite(self, test_pattern: str) -> dict:
        """指定パターンのテストスイートを実行し、結果を検証する"""
        verifier = CodeVerifier()
        try:
            return verifier.verify_dynamic(test_pattern)
        except Exception as e:
            return {"passed": False, "error": f"Test execution failed: {str(e)}"}

    def generate_tasks_for_batch(self, batch_id: str, stock_items: list) -> list:
        """Generator を使用してバッチ用のタスクを自動生成し、必要に応じて動的に分解する"""
        generator = TaskGenerator()
        raw_tasks = generator.create_batch_tasks(batch_id, stock_items)
        
        # 動的タスク分解の適用 (Stage 3 対応)
        decomposer = DynamicDecomposer()
        decomposed_tasks = []
        for task in raw_tasks:
            # 難易度や依存度に基づいてタスクを分解
            split_tasks = decomposer.decompose_task(task)
            decomposed_tasks.extend(split_tasks)
        
        # 定量的マッピング：難易度 (S/A/B/C) からタスクレベル (L1/L2) への正確な変換
        for task in decomposed_tasks:
            ds_id = task.get("design_stock_id")
            difficulty = "C"
            for item in stock_items:
                if item.get("id") == ds_id:
                    difficulty = item.get("difficulty", "C")
                    break
            
            # マッピングルール: S, A, B -> L2、C (その他) -> L1
            if difficulty in ("S", "A", "B"):
                task["level"] = "L2"
            else:
                task["level"] = "L1"
                
        return decomposed_tasks


