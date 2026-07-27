"""
Learning Loop System
Phase 7: Continuous Learning

機能:
- 2段階承認フロー（今回のみ/恒久化）
- 未来議会キュー
- 好みパターン学習
- 意思決定履歴管理
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
import json
import logging
import os
from pathlib import Path

load_dotenv_available = True
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    load_dotenv_available = False

logger = logging.getLogger(__name__)


# データ保存パスを動的に取得するヘルパー関数
def get_data_dir() -> Path:
    env_data_dir = os.environ.get("LEARNING_LOOP_DATA_DIR")
    if env_data_dir:
        return Path(env_data_dir)
    return Path(__file__).parent / "branding"


class ApprovalType(Enum):
    """承認タイプ"""
    THIS_TIME_ONLY = "this_time_only"  # 今回のみ
    PERMANENT = "permanent"  # 恒久化提案
    REJECTED = "rejected"  # 却下


@dataclass
class Decision:
    """意思決定記録"""
    id: str
    timestamp: str
    type: str  # telop, image, scene, etc.
    content: dict
    decision: str  # approved, rejected, modified
    approval_type: str  # this_time_only, permanent
    reason: str = ""
    tags: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)


@dataclass
class PermanentProposal:
    """恒久化提案"""
    id: str
    created_at: str
    source_decision_id: str
    proposal_type: str  # content_policy, keyword, style_preference
    proposal: str
    evidence: dict = field(default_factory=dict)
    status: str = "pending"  # pending, approved, rejected
    reviewed_at: str | None = None


@dataclass
class PreferencePattern:
    """好みパターン"""
    category: str  # color, position, style, etc.
    preferred: list[str] = field(default_factory=list)
    avoided: list[str] = field(default_factory=list)
    confidence: float = 0.5
    sample_count: int = 0


class LearningLoop:
    """学習ループシステム"""
    
    def __init__(self):
        data_dir = get_data_dir()
        self.decisions_path = data_dir / "decisions.json"
        self.proposals_path = data_dir / "future_council_queue.json"
        self.patterns_path = data_dir / "preference_patterns.json"
        
        self.decisions: list[Decision] = []
        self.proposals: list[PermanentProposal] = []
        self.patterns: dict[str, PreferencePattern] = {}
        
        self._load()
    
    def _load_json_data(self, file_path: Path, error_message: str) -> dict | None:
        """JSONファイルを安全に読み込むヘルパー"""
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"{error_message} (JSONデコードエラー): {e}")
            return None
        except PermissionError as e:
            logger.error(f"{error_message} (アクセス権限エラー): {e}")
            return None
        except OSError as e:
            logger.error(f"{error_message} (OSエラー): {e}")
            return None

    def _load(self):
        """データを読み込み"""
        # 意思決定履歴
        dec_data = self._load_json_data(self.decisions_path, "意思決定履歴読み込みエラー")
        if dec_data is not None:
            self.decisions = [Decision(**d) for d in dec_data.get("decisions", [])]
        
        # 未来議会キュー
        prop_data = self._load_json_data(self.proposals_path, "未来議会キュー読み込みエラー")
        if prop_data is not None:
            self.proposals = [PermanentProposal(**p) for p in prop_data.get("pending_proposals", [])]
        
        # 好みパターン
        pat_data = self._load_json_data(self.patterns_path, "好みパターン読み込みエラー")
        if pat_data is not None:
            self.patterns = {
                k: PreferencePattern(**v) for k, v in pat_data.get("patterns", {}).items()
            }
    
    def _write_json_to_fd(self, fd: int, data: dict):
        """ファイルディスクリプタにJSONデータを書き込む（内部ヘルパー）"""
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _safe_remove_temp_file(self, path: str):
        """一時ファイルを安全に削除する（内部ヘルパー）"""
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _save_atomic(self, file_path: Path, data: dict):
        """データをアトミックにJSONファイルへ保存"""
        import tempfile
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(file_path.parent), suffix=".tmp", prefix=file_path.name + "_"
        )
        
        fd_closed = False
        try:
            try:
                self._write_json_to_fd(tmp_fd, data)
                fd_closed = True
            except Exception:
                if not fd_closed:
                    try:
                        os.close(tmp_fd)
                    except OSError:
                        pass
                raise
            
            os.replace(tmp_path, str(file_path))
        except (OSError, PermissionError) as e:
            self._safe_remove_temp_file(tmp_path)
            logger.error(f"アトミック保存エラー ({file_path}): {e}")
            raise
        except Exception as e:
            self._safe_remove_temp_file(tmp_path)
            logger.error(f"アトミック保存エラー ({file_path}): {e}")
            raise

    def _save(self):
        """データを保存"""
        data_dir = get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        
        # 意思決定履歴
        self._save_atomic(self.decisions_path, {
            "version": "1.0",
            "decisions": [asdict(d) for d in self.decisions[-1000:]]  # 最新1000件
        })
        
        # 未来議会キュー
        self._save_atomic(self.proposals_path, {
            "version": "1.0",
            "pending_proposals": [asdict(p) for p in self.proposals if p.status == "pending"],
            "next_council_trigger": "session_complete"
        })
        
        # 好みパターン
        self._save_atomic(self.patterns_path, {
            "version": "1.0",
            "patterns": {k: asdict(v) for k, v in self.patterns.items()}
        })
    
    def record_decision(self, 
                        decision_type: str,
                        content: dict,
                        decision: str,
                        approval_type: ApprovalType,
                        reason: str = "",
                        tags: list[str] | None = None) -> Decision:
        """
        意思決定を記録
        
        Args:
            decision_type: telop, image, scene, etc.
            content: 対象の内容
            decision: approved, rejected, modified
            approval_type: 今回のみ or 恒久化
            reason: 理由
            tags: タグ
        
        Returns:
            Decision
        """
        if decision not in ("approved", "rejected", "modified"):
            raise ValueError(f"Invalid decision value: {decision}. Must be 'approved', 'rejected', or 'modified'.")
        if not isinstance(approval_type, ApprovalType):
            raise TypeError(f"approval_type must be an instance of ApprovalType, got {type(approval_type)}")

        dec = Decision(
            id=f"dec_{len(self.decisions):05d}",
            timestamp=datetime.now().isoformat(),
            type=decision_type,
            content=content,
            decision=decision,
            approval_type=approval_type.value,
            reason=reason,
            tags=tags or []
        )
        
        self.decisions.append(dec)
        
        # 恒久化の場合は未来議会に提案
        if approval_type == ApprovalType.PERMANENT:
            self._create_proposal(dec)
        
        # パターン学習
        self._learn_pattern(dec)
        
        self._save()
        logger.info(f"意思決定記録: {dec.id} ({decision})")
        
        return dec
    
    def _create_proposal(self, decision: Decision):
        """恒久化提案を作成"""
        proposal = PermanentProposal(
            id=f"prop_{len(self.proposals):04d}",
            created_at=datetime.now().isoformat(),
            source_decision_id=decision.id,
            proposal_type=self._infer_proposal_type(decision),
            proposal=self._generate_proposal_text(decision),
            evidence={
                "decision_type": decision.type,
                "content": decision.content,
                "reason": decision.reason
            }
        )
        self.proposals.append(proposal)
        logger.info(f"未来議会に提案追加: {proposal.id}")
    
    def _infer_proposal_type(self, decision: Decision) -> str:
        """提案タイプを推論"""
        if "style" in decision.tags or "color" in decision.tags:
            return "style_preference"
        elif "position" in decision.tags:
            return "content_policy"
        else:
            return "keyword"
    
    def _generate_proposal_text(self, decision: Decision) -> str:
        """提案テキストを生成"""
        if decision.decision == "approved":
            return f"{decision.type}で「{decision.content.get('text', '')}」スタイルを標準化"
        elif decision.decision == "rejected":
            return f"{decision.type}で「{decision.content.get('text', '')}」を避ける"
        else:
            return f"{decision.type}の修正パターンを学習"
    
    def _update_single_pattern(self, pattern: PreferencePattern, value: str, decision_status: str):
        """単一の好みパターンを更新する（内部ヘルパー）"""
        pattern.sample_count += 1
        
        if decision_status == "approved":
            if value and value not in pattern.preferred:
                pattern.preferred.append(value)
        elif decision_status == "rejected":
            if value and value not in pattern.avoided:
                pattern.avoided.append(value)
        
        # 信頼度更新
        pattern.confidence = min(1.0, pattern.sample_count / 10)

    def _learn_pattern(self, decision: Decision):
        """好みパターンを学習"""
        value = decision.content.get("value", decision.content.get("text", ""))
        for tag in decision.tags:
            if tag not in self.patterns:
                self.patterns[tag] = PreferencePattern(category=tag)
            
            self._update_single_pattern(self.patterns[tag], value, decision.decision)
    
    def get_pending_proposals(self) -> list[dict]:
        """未来議会の保留中提案を取得"""
        return [asdict(p) for p in self.proposals if p.status == "pending"]
    
    def review_proposal(self, proposal_id: str, approved: bool) -> bool:
        """提案を審議"""
        for p in self.proposals:
            if p.id == proposal_id:
                p.status = "approved" if approved else "rejected"
                p.reviewed_at = datetime.now().isoformat()
                
                if approved:
                    self._apply_to_constitution(p)
                
                self._save()
                return True
        return False
    
    def _update_constitution_content(self, constitution: dict, proposal: PermanentProposal):
        """憲法辞書データの内容を更新する（内部ヘルパー）"""
        if proposal.proposal_type == "content_policy":
            if "content_policy" not in constitution:
                constitution["content_policy"] = []
            constitution["content_policy"].append(proposal.proposal)
        elif proposal.proposal_type == "keyword":
            if "brand_personality" not in constitution:
                constitution["brand_personality"] = {"keywords": []}
            if "keywords" not in constitution["brand_personality"]:
                constitution["brand_personality"]["keywords"] = []
            # 重複チェック
            if proposal.proposal not in constitution["brand_personality"]["keywords"]:
                constitution["brand_personality"]["keywords"].append(proposal.proposal)

    def _apply_to_constitution(self, proposal: PermanentProposal):
        """憲法に適用"""
        const_path = get_data_dir() / "constitution.json"
        if not const_path.exists():
            return
        
        try:
            with open(const_path, "r", encoding="utf-8") as f:
                constitution = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"憲法適用エラー (JSONデコードエラー): {e}")
            return
        except (OSError, PermissionError) as e:
            logger.error(f"憲法適用エラー (読み込みOSエラー): {e}")
            return
        
        try:
            self._update_constitution_content(constitution, proposal)
            # アトミックに保存
            self._save_atomic(const_path, constitution)
            logger.info(f"憲法に適用: {proposal.proposal}")
        except KeyError as e:
            logger.error(f"憲法適用エラー (キーエラー): {e}")
        except (OSError, PermissionError) as e:
            logger.error(f"憲法適用エラー (書き込みOSエラー): {e}")
    
    def get_preferences(self, category: str | None = None) -> dict:
        """好みパターンを取得"""
        if category:
            pattern = self.patterns.get(category)
            return asdict(pattern) if pattern else {}
        return {k: asdict(v) for k, v in self.patterns.items()}
    
    def apply_preferences(self, proposal: dict, category: str) -> dict:
        """好みを提案に適用"""
        pattern = self.patterns.get(category)
        if not pattern:
            return proposal
        
        # 好みを反映
        if "style" in proposal and pattern.preferred:
            # 好みのスタイルを優先
            proposal["recommended_styles"] = pattern.preferred[:3]
        
        if pattern.avoided:
            proposal["avoid_styles"] = pattern.avoided
        
        return proposal


# シングルトンインスタンス
learning_loop = LearningLoop()


def record_approval(content: dict, tags: list[str] | None = None, permanent: bool = False) -> Decision:
    """承認を記録（簡易関数）"""
    approval_type = ApprovalType.PERMANENT if permanent else ApprovalType.THIS_TIME_ONLY
    return learning_loop.record_decision(
        decision_type=content.get("type", "general"),
        content=content,
        decision="approved",
        approval_type=approval_type,
        tags=tags or []
    )


def record_rejection(content: dict, reason: str = "", tags: list[str] | None = None) -> Decision:
    """却下を記録（簡易関数）"""
    return learning_loop.record_decision(
        decision_type=content.get("type", "general"),
        content=content,
        decision="rejected",
        approval_type=ApprovalType.THIS_TIME_ONLY,
        reason=reason,
        tags=tags or []
    )


def get_council_agenda() -> list[dict]:
    """未来議会の議題を取得（簡易関数）"""
    return learning_loop.get_pending_proposals()
