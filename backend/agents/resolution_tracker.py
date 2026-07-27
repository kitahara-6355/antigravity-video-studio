import os
import json
import time
import logging
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict
from pathlib import Path
from safe_io import SafeJsonStore

logger = logging.getLogger(__name__)

class ResolutionStatus(str, Enum):
    """議案のステータス（みらい議会スタイル）"""
    DRAFT = "draft"  # 提案中
    DEBATE = "debate"  # 議論中
    VOTING = "voting"  # 承認待ち
    APPROVED = "approved"  # 可決
    REJECTED = "rejected"  # 否決

class Resolution:
    """
    議会の決議案（みらい議会コンセプト）
    AI議論の成果を「法案」として管理し、議長（ユーザー）の承認を経て憲法に反映。
    """
    def __init__(
        self,
        resolution_id: str,
        title: str,
        description: str,
        proposed_changes: Dict,
        session_id: str
    ):
        self.id = resolution_id
        self.title = title
        self.description = description
        self.proposed_changes = proposed_changes  # Constitution への変更内容
        self.session_id = session_id
        self.status = ResolutionStatus.DRAFT
        self.votes = {}  # {agent_name: "APPROVE" | "REJECT"}
        self.created_at = time.time()
        self.updated_at = time.time()
        self.gavel_decision = None  # "APPROVE" | "REJECT" by Chairman
        
    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "proposed_changes": self.proposed_changes,
            "session_id": self.session_id,
            "status": self.status,
            "votes": self.votes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "gavel_decision": self.gavel_decision,
            "progress": self._calculate_progress()
        }
    
    def _calculate_progress(self) -> float:
        """議論の進捗度を計算（0.0-1.0）"""
        status_progress = {
            ResolutionStatus.DRAFT: 0.2,
            ResolutionStatus.DEBATE: 0.5,
            ResolutionStatus.VOTING: 0.8,
            ResolutionStatus.APPROVED: 1.0,
            ResolutionStatus.REJECTED: 1.0
        }
        return status_progress.get(self.status, 0.0)

class ResolutionTracker:
    """
    議案トラッカー（みらい議会スタイル）
    """
    def __init__(self, archive_dir="archives/resolutions"):
        self.archive_dir = archive_dir
        if not os.path.exists(self.archive_dir):
            os.makedirs(self.archive_dir)
        self.active_resolutions: Dict[str, Resolution] = {}
        
    def create_resolution(
        self,
        title: str,
        description: str,
        proposed_changes: Dict,
        session_id: str
    ) -> Resolution:
        """新しい議案を作成"""
        import uuid
        resolution_id = str(uuid.uuid4())
        resolution = Resolution(resolution_id, title, description, proposed_changes, session_id)
        self.active_resolutions[resolution_id] = resolution
        self._save_resolution(resolution)
        return resolution
    
    def _update_and_save(self, resolution: Resolution):
        """状態の更新日時を記録し、保存する"""
        resolution.updated_at = time.time()
        self._save_resolution(resolution)

    def update_status(self, resolution_id: str, new_status: ResolutionStatus):
        """ステータスを更新"""
        if resolution_id in self.active_resolutions:
            resolution = self.active_resolutions[resolution_id]
            resolution.status = new_status
            self._update_and_save(resolution)
    
    def record_vote(self, resolution_id: str, agent_name: str, vote: str):
        """エージェントの投票を記録"""
        if resolution_id in self.active_resolutions:
            resolution = self.active_resolutions[resolution_id]
            resolution.votes[agent_name] = vote
            self._update_and_save(resolution)
            
    def apply_gavel(self, resolution_id: str, decision: str) -> bool:
        """議長決済を適用"""
        if resolution_id not in self.active_resolutions:
            return False
        
        resolution = self.active_resolutions[resolution_id]
        resolution.gavel_decision = decision
        
        if decision == "APPROVE":
            resolution.status = ResolutionStatus.APPROVED
        else:
            resolution.status = ResolutionStatus.REJECTED
            
        self._update_and_save(resolution)
        return True
    
    def get_resolution(self, resolution_id: str) -> Optional[Resolution]:
        """議案を取得"""
        return self.active_resolutions.get(resolution_id)
    
    def list_resolutions(self, status: Optional[ResolutionStatus] = None) -> List[Dict]:
        """議案一覧を取得"""
        resolutions = list(self.active_resolutions.values())
        if status:
            resolutions = [r for r in resolutions if r.status == status]
        return [r.to_dict() for r in sorted(resolutions, key=lambda x: x.updated_at, reverse=True)]
    
    def _save_resolution(self, resolution: Resolution):
        """議案をファイルに保存"""
        filename = f"resolution_{resolution.id}.json"
        filepath = os.path.join(self.archive_dir, filename)
        try:
            store = SafeJsonStore(Path(filepath))
            store.save(resolution.to_dict())
        except OSError as e:
            logger.error(f"Failed to save resolution {resolution.id}: {e}")

# Singleton
resolution_tracker = ResolutionTracker()
