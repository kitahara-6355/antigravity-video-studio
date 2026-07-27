"""
Decision Logger - 意思決定記録システム

Progressive Quality Pipeline 追加機能
ユーザーの意思決定を記録し、AIが学習・参照できる仕組み

【PROJECT_CONSTITUTION 整合性】
- Soul Narrative (8.4) との統合
- 意思決定 = 監督の「判断の軌跡」として成長物語に記録
- evolution_log.json に統合保存

解決する課題:
1. 同じ意思決定を繰り返すリスク → 過去の判断を参照
2. 意思決定の理由がAIに伝わらないリスク → コンテキスト生成
3. 過去の判断を次の編集に活かせないリスク → AI学習機能

設計思想:
- 意思決定 = 単なるログではなく「監督の成長記録」
- 却下理由 = 「こだわり」として哲学に昇華
- 承認パターン = 「好み」として次回提案に反映
"""

import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    """意思決定レコード"""
    decision_id: str
    timestamp: float
    iso_time: str
    
    # 対象
    target_type: str  # "screenshot", "draft", "prefinal"
    target_path: str
    target_description: str
    
    # 意思決定
    decision: str  # "approve", "reject", "modify"
    reason: str  # ユーザーが入力した理由
    
    # コンテキスト
    scene_info: Dict = None      # シーン番号、タイムスタンプなど
    mood_settings: Dict = None   # 適用中のムード設定
    
    # AI学習用
    tags: List[str] = None       # ["色調整", "テンポ", "字幕位置"]
    learned: bool = False        # AIが学習済みか


class DecisionLogger:
    """意思決定記録・学習システム"""
    
    def __init__(self):
        """初期化"""
        base_dir = Path(__file__).parent
        self.log_dir = base_dir / "branding"
        self.log_file = self.log_dir / "decision_log.json"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # ログ読み込み
        self.decisions: List[Decision] = []
        self._load()
    
    def _load(self):
        """ログファイルを読み込み"""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.decisions = [
                        Decision(**d) for d in data.get("decisions", [])
                    ]
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in decision log: {e}")
                self.decisions = []
            except FileNotFoundError as e:
                logger.error(f"Decision log file not found: {e}")
                self.decisions = []
            except PermissionError as e:
                logger.error(f"Permission denied reading decision log: {e}")
                self.decisions = []
            except (TypeError, KeyError, OSError) as e:
                logger.error(f"Failed to load decision log: {e}")
                self.decisions = []
    
    def _save(self):
        """ログファイルを保存"""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "decisions": [asdict(d) for d in self.decisions],
                    "last_updated": datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
        except PermissionError as e:
            logger.error(f"Permission denied writing decision log: {e}")
        except TypeError as e:
            logger.error(f"Type error encoding decision log to JSON: {e}")
        except OSError as e:
            logger.error(f"Failed to save decision log: {e}")
    
    def record_decision(
        self,
        target_type: str,
        target_path: str,
        target_description: str,
        decision: str,
        reason: str,
        scene_info: Dict = None,
        mood_settings: Dict = None,
        tags: List[str] = None
    ) -> str:
        """
        意思決定を記録
        
        Args:
            target_type: 対象タイプ（screenshot/draft/prefinal）
            target_path: 対象ファイルパス
            target_description: 対象の説明
            decision: 判断（approve/reject/modify）
            reason: 判断理由（ユーザー入力）
            scene_info: シーン情報
            mood_settings: ムード設定
            tags: タグ（AI分類用）
        
        Returns:
            decision_id
        """
        import uuid
        
        decision_record = Decision(
            decision_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            iso_time=datetime.now().isoformat(),
            target_type=target_type,
            target_path=target_path,
            target_description=target_description,
            decision=decision,
            reason=reason,
            scene_info=scene_info or {},
            mood_settings=mood_settings or {},
            tags=tags or [],
            learned=False
        )
        
        self.decisions.append(decision_record)
        self._save()
        
        logger.info(f"📝 Decision recorded: {decision} - {reason[:50]}...")
        
        return decision_record.decision_id
    
    def get_similar_decisions(
        self,
        target_type: str = None,
        tags: List[str] = None,
        limit: int = 5
    ) -> List[Decision]:
        """
        類似の過去の意思決定を取得
        
        AIが同じ判断を繰り返さないように、
        過去の類似ケースを参照する
        
        Args:
            target_type: 対象タイプでフィルタ
            tags: タグでフィルタ
            limit: 最大件数
        
        Returns:
            類似の意思決定リスト
        """
        filtered = self.decisions
        
        if target_type:
            filtered = [d for d in filtered if d.target_type == target_type]
        
        if tags:
            filtered = [
                d for d in filtered 
                if d.tags and any(t in d.tags for t in tags)
            ]
        
        # 新しい順にソート
        filtered = sorted(filtered, key=lambda x: x.timestamp, reverse=True)
        
        return filtered[:limit]
    
    def get_ai_context(self, target_type: str = None) -> str:
        """
        AIに渡すコンテキストを生成
        
        過去の意思決定を要約して、
        AIが同じ質問を繰り返さないようにする
        
        Args:
            target_type: 対象タイプ
        
        Returns:
            AIプロンプトに追加するコンテキスト文字列
        """
        recent = self.get_similar_decisions(target_type, limit=10)
        
        if not recent:
            return ""
        
        context_lines = [
            "## ユーザーの過去の意思決定（必ず参照すること）",
            ""
        ]
        
        for d in recent:
            context_lines.append(
                f"- [{d.iso_time[:10]}] {d.target_description}: "
                f"**{d.decision}** - {d.reason}"
            )
        
        context_lines.append("")
        context_lines.append(
            "上記の意思決定を尊重し、同じ質問を繰り返さないでください。"
        )
        
        return "\n".join(context_lines)
    
    def get_rejection_patterns(self) -> Dict[str, int]:
        """
        却下パターンを分析
        
        どのような変更が却下されやすいかを把握
        
        Returns:
            タグ別の却下回数
        """
        rejections = [d for d in self.decisions if d.decision == "reject"]
        
        patterns = {}
        for d in rejections:
            for tag in (d.tags or []):
                patterns[tag] = patterns.get(tag, 0) + 1
        
        return dict(sorted(patterns.items(), key=lambda x: x[1], reverse=True))
    
    def mark_as_learned(self, decision_id: str):
        """意思決定をAI学習済みとしてマーク"""
        for d in self.decisions:
            if d.decision_id == decision_id:
                d.learned = True
                self._save()
                return True
        return False
    
    def get_stats(self) -> Dict:
        """意思決定統計を取得"""
        total = len(self.decisions)
        approvals = len([d for d in self.decisions if d.decision == "approve"])
        rejections = len([d for d in self.decisions if d.decision == "reject"])
        modifications = len([d for d in self.decisions if d.decision == "modify"])
        learned = len([d for d in self.decisions if d.learned])
        
        return {
            "total_decisions": total,
            "approvals": approvals,
            "rejections": rejections,
            "modifications": modifications,
            "learned_by_ai": learned,
            "approval_rate": round(approvals / total * 100, 1) if total > 0 else 0,
            "rejection_patterns": self.get_rejection_patterns()
        }
    
    # ===== Soul Narrative 統合 (PROJECT_CONSTITUTION 8.4) =====
    
    def sync_to_soul_narrative(self):
        """
        意思決定をSoul Narrative（evolution_log）に同期
        
        却下理由を「こだわり」として哲学に昇華
        承認パターンを「好み」として記録
        """
        evolution_log_path = self.log_dir / "evolution_log.json"
        
        # evolution_log読み込み
        if evolution_log_path.exists():
            with open(evolution_log_path, 'r', encoding='utf-8') as f:
                evo_log = json.load(f)
        else:
            evo_log = {"entries": [], "philosophies": [], "decision_insights": []}
        
        # 未同期の意思決定を取得
        unsynced = [d for d in self.decisions if not d.learned]
        
        if not unsynced:
            return {"synced": 0, "new_insights": []}
            
        # Wagamama Ledger Integration (Auto Pain Detection & Resolution)
        try:
            from wagamama_manager import wagamama_manager
            
            # 1. 却下・修正（reject/modify）パターンからの自動起票 (Pain Detection)
            for dec in unsynced:
                if dec.decision in ("reject", "modify"):
                    # 共通タグについて、直近2回連続での却下・修正をスキャン
                    for tag in (dec.tags or []):
                        if tag.startswith("wagamama_id:"):
                            continue
                        
                        # 過去の decisions から同じタグを持つ直前の決定を探す
                        prev_dec = None
                        try:
                            idx = self.decisions.index(dec)
                            search_slice = self.decisions[:idx]
                        except ValueError:
                            search_slice = self.decisions
                            
                        for p in reversed(search_slice):
                            if p.tags and tag in p.tags:
                                prev_dec = p
                                break
                        
                        if prev_dec and prev_dec.decision in ("reject", "modify"):
                            # 2回連続で却下/修正が発生。進行中のストーリーが既に存在するかチェック
                            existing_id = wagamama_manager.find_matching_story(topic="", tags=[tag])
                            if not existing_id:
                                # 新規起票
                                w_id = wagamama_manager.create_experience_story(
                                    user_voice=dec.reason,
                                    detected_by="decision_logger",
                                    feature_id=tag
                                )
                                if dec.tags is None:
                                    dec.tags = []
                                dec.tags.append(f"wagamama_id:{w_id}")
                                logger.info(f"Auto created story {w_id} for tag '{tag}' due to consecutive rejections.")
                                break # 1つの決定に対して1回起票すれば十分
            
            # 2. 承認（approve）時の自動解決と品質ギャップ検証
            for dec in unsynced:
                if dec.decision == "approve":
                    w_id = None
                    if dec.tags:
                        for tag in dec.tags:
                            if tag.startswith("wagamama_id:"):
                                w_id = tag.split(":")[1]
                                break
                    
                    if not w_id and dec.tags:
                        w_id = wagamama_manager.find_matching_story(topic=dec.target_description, tags=dec.tags)
                        
                    if w_id:
                        wagamama_manager.resolve_story(
                             wagamama_id=w_id,
                             solution_description=dec.reason or f"Approved: {dec.target_description}",
                             emotion="満足"
                        )
        except ImportError:
            pass

        
        # 意思決定を分析してインサイトを生成
        new_insights = []
        
        # 却下パターンから「こだわり」を抽出
        rejection_reasons = [d.reason for d in unsynced if d.decision == "reject"]
        if rejection_reasons:
            insight = {
                "type": "preference",
                "timestamp": datetime.now().isoformat(),
                "source": "rejection_analysis",
                "content": f"却下理由から抽出: {', '.join(rejection_reasons[:3])}",
                "decision_ids": [d.decision_id for d in unsynced if d.decision == "reject"]
            }
            new_insights.append(insight)
        
        # 承認パターンから「好み」を抽出
        approval_tags = []
        for d in unsynced:
            if d.decision == "approve" and d.tags:
                approval_tags.extend(d.tags)
        
        if approval_tags:
            # 頻出タグを抽出
            tag_counts = {}
            for tag in approval_tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            
            insight = {
                "type": "style_preference",
                "timestamp": datetime.now().isoformat(),
                "source": "approval_analysis",
                "content": f"好みのスタイル: {', '.join([t[0] for t in top_tags])}",
                "decision_ids": [d.decision_id for d in unsynced if d.decision == "approve"]
            }
            new_insights.append(insight)
        
        # evolution_logに追加
        if "decision_insights" not in evo_log:
            evo_log["decision_insights"] = []
        
        evo_log["decision_insights"].extend(new_insights)
        
        # entriesにも要約を追加
        if unsynced:
            summary_entry = {
                "timestamp": time.time(),
                "iso_time": datetime.now().isoformat(),
                "type": "decision_sync",
                "summary": f"{len(unsynced)}件の意思決定を同期",
                "insight": self._generate_insight_summary(unsynced),
                "stat_changes": [
                    f"Decisions +{len(unsynced)}",
                    f"Approval Rate: {self.get_stats()['approval_rate']}%"
                ]
            }
            evo_log["entries"].append(summary_entry)
        
        # 保存
        with open(evolution_log_path, 'w', encoding='utf-8') as f:
            json.dump(evo_log, f, ensure_ascii=False, indent=2)
        
        # 同期済みとしてマーク
        for d in unsynced:
            d.learned = True
        self._save()
        
        logger.info(f"✅ Soul Narrative synced: {len(unsynced)} decisions, {len(new_insights)} insights")
        
        return {
            "synced": len(unsynced),
            "new_insights": new_insights
        }
    
    def _generate_insight_summary(self, decisions: List[Decision]) -> str:
        """意思決定からAI向けインサイトを生成"""
        approvals = [d for d in decisions if d.decision == "approve"]
        rejections = [d for d in decisions if d.decision == "reject"]
        
        parts = []
        
        if rejections:
            parts.append(
                f"却下された{len(rejections)}件の判断から、"
                f"監督のこだわりが見えてきました: "
                f"{rejections[0].reason[:50]}..."
            )
        
        if approvals:
            parts.append(
                f"承認された{len(approvals)}件の判断は、"
                f"監督の好みを反映しています。"
            )
        
        return " ".join(parts) or "新しい意思決定が記録されました。"
    
    def get_director_preferences(self) -> Dict:
        """
        監督の好み・こだわりを取得
        
        AIが提案する際に参照する「監督プロファイル」
        """
        stats = self.get_stats()
        rejection_patterns = stats["rejection_patterns"]
        
        # 好みのスタイルを推定
        approval_tags = []
        for d in self.decisions:
            if d.decision == "approve" and d.tags:
                approval_tags.extend(d.tags)
        
        preferred_styles = {}
        for tag in approval_tags:
            preferred_styles[tag] = preferred_styles.get(tag, 0) + 1
        
        return {
            "こだわり（却下傾向）": rejection_patterns,
            "好み（承認傾向）": dict(sorted(preferred_styles.items(), key=lambda x: x[1], reverse=True)),
            "承認率": stats["approval_rate"],
            "総判断数": stats["total_decisions"],
            "AI提案へのアドバイス": self._generate_advice()
        }
    
    def _generate_advice(self) -> str:
        """AIへのアドバイスを生成"""
        patterns = self.get_rejection_patterns()
        
        if not patterns:
            return "まだ十分なデータがありません。"
        
        top_rejection = list(patterns.keys())[0] if patterns else None
        
        if top_rejection:
            return f"「{top_rejection}」に関する提案は慎重に。過去に却下されています。"
        
        return "監督の好みを学習中です。"
    
    def sync_to_evolution_log(self):
        """
        trinity.py互換エイリアス: sync_to_soul_narrativeへ委譲
        
        Phase 4 (M4.1) で EvolutionSyncService に統合予定。
        """
        return self.sync_to_soul_narrative()


# シングルトンインスタンス
decision_logger = DecisionLogger()
