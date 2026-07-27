"""
TaskContract — Claude Code 由来の「成功条件定義」

Claude Code の Coordinator が各 Worker に付与していた
「Definition of Done（完了定義）」を Antigravity に移植。

設計根拠:
    Claude Code 流出コードの解析で判明した重要な知見:
    - Coordinator はタスクを振る際、内容だけでなく
      「このタスクが成功したと言える客観的な証拠」を定義していた
    - Worker は証拠を提示できない限り「完了」を報告できない
    - これにより、モデルの「気分」に依存しない堅牢な判定が実現

    Antigravity では Council / ProductionPipeline の両系統で使用。
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """タスクの状態"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_REVIEW = "awaiting_review"
    PASSED = "passed"
    FAILED = "failed"
    ESCALATED = "escalated"  # Circuit Breaker 発火時


class EvidenceType(Enum):
    """証拠のタイプ"""
    FILE_EXISTS = "file_exists"         # 特定ファイルの存在
    FILE_CONTENT = "file_content"       # ファイル内容 of 条件
    API_RESPONSE = "api_response"       # API レスポンス of 条件
    SCORE_THRESHOLD = "score_threshold" # スコアしきい値
    LOG_CONTAINS = "log_contains"       # ログに特定文字列
    CUSTOM = "custom"                   # カスタム検証関数
    THUMBNAIL_QUALITY = "thumbnail_quality"  # サムネイル品質検証


@dataclass
class EvidenceRequirement:
    """タスク成功の証拠要件"""
    evidence_type: str  # EvidenceType の値
    description: str
    verification_data: Dict = field(default_factory=dict)
    # 例: {"path": "output/final.mp4", "min_size_bytes": 1024}
    #     {"score_key": "quality", "min_value": 80}
    satisfied: bool = False
    satisfied_at: Optional[str] = None


@dataclass
class TaskContract:
    """
    Coordinator が各 Worker に付与する「成功条件」定義。

    Claude Code 由来:
    - タスク内容だけでなく「成功の客観的証拠」を必ず定義
    - Worker はこの証拠を提示できない限り「完了」を報告できない
    - 失敗時のフォールバック戦略も事前に定義

    Usage:
        contract = TaskContract(
            task_id="transcribe_001",
            description="動画ファイルを文字起こしする",
            definition_of_done="字幕セグメントが1件以上生成され、各セグメントにタイムスタンプが付与されていること",
            evidence_required=[
                EvidenceRequirement(
                    evidence_type="score_threshold",
                    description="セグメント数が1以上",
                    verification_data={"key": "segments_count", "min_value": 1}
                )
            ]
        )
    """
    task_id: str
    description: str
    definition_of_done: str
    evidence_required: List[EvidenceRequirement] = field(default_factory=list)
    status: str = "pending"  # TaskStatus の値
    max_retries: int = 3
    timeout_seconds: int = 300
    fallback_strategy: str = "report_to_coordinator"
    # "retry_with_modification", "escalate", "skip_with_warning", "report_to_coordinator"

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    error_history: List[Dict] = field(default_factory=list)


class TaskContractManager:
    """
    TaskContract のライフサイクル管理。

    Coordinator（Council / Pipeline）が使用する。
    """

    def __init__(self):
        self.active_contracts: Dict[str, TaskContract] = {}
        self.completed_contracts: List[TaskContract] = []

    # ============================================================
    # 契約の作成
    # ============================================================

    def create_contract(
        self,
        task_id: str,
        description: str,
        definition_of_done: str,
        evidence: Optional[List[Dict]] = None,
        max_retries: int = 3,
        timeout_seconds: int = 300,
        fallback_strategy: str = "report_to_coordinator",
    ) -> TaskContract:
        """
        新しい TaskContract を作成。

        Args:
            task_id: タスク識別子
            description: タスクの説明
            definition_of_done: 成功条件の人間可読な定義
            evidence: 証拠要件のリスト
            max_retries: 最大リトライ回数
            timeout_seconds: タイムアウト秒数
            fallback_strategy: 失敗時のフォールバック戦略
        """
        if not task_id or not isinstance(task_id, str):
            raise ValueError("task_id must be a non-empty string")

        safe_desc = description if isinstance(description, str) else ""
        safe_dod = definition_of_done if isinstance(definition_of_done, str) else ""

        safe_max_retries = max_retries if isinstance(max_retries, int) and max_retries >= 0 else 3
        safe_timeout = timeout_seconds if isinstance(timeout_seconds, int) and timeout_seconds >= 0 else 300
        safe_fallback = fallback_strategy if isinstance(fallback_strategy, str) else "report_to_coordinator"

        evidence_reqs = []
        if isinstance(evidence, list):
            for ev in evidence:
                if not isinstance(ev, dict):
                    continue
                ev_type = ev.get("type", "custom")
                if not isinstance(ev_type, str):
                    ev_type = "custom"
                ev_desc = ev.get("description", "")
                if not isinstance(ev_desc, str):
                    ev_desc = ""
                ev_data = ev.get("data", {})
                if not isinstance(ev_data, dict):
                    ev_data = {}
                evidence_reqs.append(EvidenceRequirement(
                    evidence_type=ev_type,
                    description=ev_desc,
                    verification_data=ev_data,
                ))

        contract = TaskContract(
            task_id=task_id,
            description=safe_desc,
            definition_of_done=safe_dod,
            evidence_required=evidence_reqs,
            max_retries=safe_max_retries,
            timeout_seconds=safe_timeout,
            fallback_strategy=safe_fallback,
        )

        self.active_contracts[task_id] = contract
        logger.info(f"📋 Contract作成: {task_id} — DoD: {safe_dod[:60]}...")
        return contract

    # ============================================================
    # 契約の実行管理
    # ============================================================

    def start_task(self, task_id: str) -> Optional[TaskContract]:
        """タスクの実行開始を記録"""
        if not task_id or not isinstance(task_id, str):
            return None
        contract = self.active_contracts.get(task_id)
        if contract:
            if contract.started_at is None:
                contract.started_at = datetime.now().isoformat()
            contract.status = TaskStatus.IN_PROGRESS.value
            logger.info(f"▶️ Task開始: {task_id}")
        return contract

    def submit_evidence(
        self, task_id: str, evidence_data: Dict
    ) -> Optional[TaskContract]:
        """
        Worker が証拠を提出。

        Args:
            task_id: タスク識別子
            evidence_data: 証拠データ（キー: 値）
        """
        if not task_id or not isinstance(task_id, str):
            return None
        contract = self.active_contracts.get(task_id)
        if not contract:
            return None

        # すでに完了している場合は証拠を受け入れない
        if contract.status in (TaskStatus.PASSED.value, TaskStatus.FAILED.value, TaskStatus.ESCALATED.value):
            return contract

        safe_data = evidence_data if isinstance(evidence_data, dict) else {}

        for req in contract.evidence_required:
            if req.satisfied:
                continue

            if self._verify_evidence(req, safe_data):
                req.satisfied = True
                req.satisfied_at = datetime.now().isoformat()
                logger.info(f"  ✅ 証拠充足: {req.description}")

        return contract

    def check_completion(self, task_id: str) -> Dict:
        """
        タスクの完了判定。

        Returns:
            {
                "completed": bool,
                "all_evidence_satisfied": bool,
                "missing_evidence": List[str],
                "status": str
            }
        """
        if not task_id or not isinstance(task_id, str):
            return {"completed": False, "error": "Contract not found"}
        contract = self.active_contracts.get(task_id)
        if not contract:
            return {"completed": False, "error": "Contract not found"}

        # すでに完了している場合は重複してアーカイブしない
        if contract.status == TaskStatus.PASSED.value:
            return {
                "completed": True,
                "all_evidence_satisfied": True,
                "missing_evidence": [],
                "status": contract.status,
            }

        missing = [
            req.description
            for req in contract.evidence_required
            if not req.satisfied
        ]

        all_satisfied = len(missing) == 0

        if all_satisfied:
            contract.status = TaskStatus.PASSED.value
            contract.completed_at = datetime.now().isoformat()
            self._archive_contract(task_id)
            logger.info(f"✅ Task完了: {task_id}")

        return {
            "completed": all_satisfied,
            "all_evidence_satisfied": all_satisfied,
            "missing_evidence": missing,
            "status": contract.status,
        }

    def report_failure(
        self, task_id: str, error: str, context: Optional[Dict] = None
    ) -> Dict:
        """
        Worker が失敗を報告。

        Circuit Breaker パターン:
        - max_retries 以内 → リトライ許可
        - max_retries 超過 → フォールバック戦略実行
        """
        if not task_id or not isinstance(task_id, str):
            return {"action": "abort", "reason": "Contract not found"}
        contract = self.active_contracts.get(task_id)
        if not contract:
            return {"action": "abort", "reason": "Contract not found"}

        # すでに完了している場合は報告を受け入れない
        if contract.status in (TaskStatus.PASSED.value, TaskStatus.FAILED.value, TaskStatus.ESCALATED.value):
            return {"action": "abort", "reason": "Task already terminated", "status": contract.status}

        safe_error = error if isinstance(error, str) else str(error)
        safe_context = context if isinstance(context, dict) else {}

        contract.retry_count += 1
        contract.error_history.append({
            "attempt": contract.retry_count,
            "error": safe_error,
            "context": safe_context,
            "timestamp": datetime.now().isoformat(),
        })

        if contract.retry_count >= contract.max_retries:
            # Circuit Breaker 発火
            contract.status = TaskStatus.ESCALATED.value
            logger.warning(
                f"⚡ Circuit Breaker発火: {task_id} "
                f"({contract.retry_count}/{contract.max_retries}回失敗)"
            )
            return {
                "action": contract.fallback_strategy,
                "reason": f"{contract.max_retries}回連続失敗",
                "error_history": contract.error_history,
            }

        logger.info(
            f"🔄 リトライ許可: {task_id} "
            f"({contract.retry_count}/{contract.max_retries})"
        )
        return {
            "action": "retry",
            "attempt": contract.retry_count,
            "max_retries": contract.max_retries,
            "previous_errors": [e["error"] for e in contract.error_history],
        }

    # ============================================================
    # 証拠検証
    # ============================================================

    def _verify_evidence(
        self, requirement: EvidenceRequirement, data: Dict
    ) -> bool:
        """証拠要件を検証"""
        if not requirement or not isinstance(requirement, EvidenceRequirement):
            return False
        if not isinstance(data, dict):
            return False

        ev_type = requirement.evidence_type
        ver_data = requirement.verification_data
        if not isinstance(ver_data, dict):
            return False

        if ev_type == EvidenceType.FILE_EXISTS.value:
            from pathlib import Path
            path = ver_data.get("path", "")
            if not path or not isinstance(path, (str, Path)):
                return False
            try:
                path_obj = Path(path)
                exists = path_obj.exists()
                if exists and "min_size_bytes" in ver_data:
                    min_size = ver_data["min_size_bytes"]
                    if isinstance(min_size, (int, float)):
                        return path_obj.stat().st_size >= min_size
                    return False
                return exists
            except OSError as e:
                logger.warning(f"File system verification failed for path '{path}': {e}")
                return False

        elif ev_type == EvidenceType.SCORE_THRESHOLD.value:
            key = ver_data.get("key", "")
            if not isinstance(key, str) or not key:
                return False
            min_val = ver_data.get("min_value", 0)
            actual = data.get(key, 0)
            if isinstance(min_val, (int, float)) and isinstance(actual, (int, float)):
                return actual >= min_val
            return False

        elif ev_type == EvidenceType.LOG_CONTAINS.value:
            log_key = ver_data.get("log_key", "")
            expected = ver_data.get("contains", "")
            if not isinstance(log_key, str) or not log_key:
                return False
            if not isinstance(expected, str):
                return False
            actual = data.get(log_key, "")
            if isinstance(actual, str):
                return expected in actual
            return False

        elif ev_type == EvidenceType.CUSTOM.value:
            # カスタム検証: data 内に "verified" キーがあり、それが True と評価されれば通過
            return bool(data.get("verified", False))

        elif ev_type == "thumbnail_quality" or ev_type == EvidenceType.THUMBNAIL_QUALITY.value:
            from pathlib import Path
            from PIL import Image
            path = ver_data.get("path", "")
            if not path or not isinstance(path, (str, Path)):
                return False
            try:
                path_obj = Path(path)
                if not path_obj.exists():
                    logger.warning(f"Thumbnail file does not exist: {path}")
                    return False
                
                size_bytes = path_obj.stat().st_size
                if size_bytes >= 4 * 1024 * 1024:
                    logger.warning(f"Thumbnail file size {size_bytes} exceeds 4MB limit.")
                    return False
                
                try:
                    with Image.open(path_obj) as img:
                        img.verify()
                except Exception as e:
                    logger.warning(f"Thumbnail image verify failed: {e}")
                    return False
                
                try:
                    with Image.open(path_obj) as img:
                        img.load()
                        width, height = img.size
                except Exception as e:
                    logger.warning(f"Thumbnail image load failed: {e}")
                    return False
                
                if width < 1280 or height < 720:
                    logger.warning(f"Thumbnail resolution {width}x{height} is below 1280x720 limit.")
                    return False
                
                aspect_ratio = width / height
                target_ratio = 16.0 / 9.0
                if abs(aspect_ratio - target_ratio) > 1e-3:
                    logger.warning(f"Thumbnail aspect ratio {aspect_ratio:.3f} is not 16:9.")
                    return False
                
                return True
            except OSError as e:
                logger.warning(f"OS error during thumbnail verification: {e}")
                return False
            except Exception as e:
                logger.warning(f"Unexpected error during thumbnail verification: {e}")
                return False

        return False

    # ============================================================
    # ヘルパー
    # ============================================================

    def _archive_contract(self, task_id: str):
        """完了した契約をアーカイブ"""
        contract = self.active_contracts.pop(task_id, None)
        if contract:
            self.completed_contracts.append(contract)

    def get_pipeline_contracts(self) -> List[Dict]:
        """ProductionPipeline 用の標準契約セットを生成"""
        return [
            {
                "task_id": "transcribe",
                "description": "動画ファイルを文字起こし",
                "definition_of_done": "字幕セグメントが1件以上生成され、各セグメントにタイムスタンプが付与",
                "evidence": [
                    {"type": "score_threshold", "description": "セグメント数≥1",
                     "data": {"key": "segments_count", "min_value": 1}},
                ],
            },
            {
                "task_id": "proofread",
                "description": "字幕テキストのAI校閲",
                "definition_of_done": "全セグメントが校閲済みで、固有名詞誤りがゼロ",
                "evidence": [
                    {"type": "score_threshold", "description": "校閲済みセグメント数≥1",
                     "data": {"key": "corrected_count", "min_value": 1}},
                ],
            },
            {
                "task_id": "quality_gate",
                "description": "品質チェック",
                "definition_of_done": "品質スコア90点以上かつ致命的エラーゼロ",
                "evidence": [
                    {"type": "score_threshold", "description": "品質スコア≥90",
                     "data": {"key": "quality_score", "min_value": 90}},
                ],
            },
            {
                "task_id": "render",
                "description": "最終レンダリング",
                "definition_of_done": "出力ファイルが存在し、サイズが1MB以上",
                "evidence": [
                    {"type": "file_exists", "description": "出力ファイル存在",
                     "data": {"path": "", "min_size_bytes": 1_000_000}},
                ],
            },
            {
                "task_id": "thumbnail",
                "description": "A/Bテスト用サムネイル候補および画像の生成",
                "definition_of_done": "3パターンのサムネイル候補（画像ファイル）が正常に生成されていること",
                "evidence": [
                    {"type": "file_exists", "description": "サムネイル画像ファイル存在",
                     "data": {"path": "output/thumbnails/", "min_size_bytes": 1000}},
                ],
            },
        ]

    def get_stats(self) -> Dict:
        """契約管理の統計"""
        return {
            "active": len(self.active_contracts),
            "completed": len(self.completed_contracts),
            "passed": len([c for c in self.completed_contracts if c.status == "passed"]),
            "escalated": len([
                c for c in list(self.active_contracts.values()) + self.completed_contracts
                if c.status == "escalated"
            ]),
        }


# ============================================================
# シングルトンインスタンス
# ============================================================
task_contract_manager = TaskContractManager()