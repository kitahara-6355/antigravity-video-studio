"""
SmartCutPlugin - スマートカット機能

実装計画準拠:
- 動的尺調整（15/30/45/60分）
- 固定シーン機能
- AI推奨構成
- セマンティック境界調整
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
import json
import logging

from core.plugin import Plugin, PluginPhase
from core.context import ProductionContext

logger = logging.getLogger(__name__)


@dataclass
class LockedSegment:
    """ユーザー固定シーン"""
    id: str
    start_time: float
    end_time: float
    title: str
    reason: str = ""  # なぜ固定したか（Soul Narrative用）
    locked_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class SegmentCandidate:
    """セグメント候補"""
    id: str
    start_time: float
    end_time: float
    title: str
    score: float
    type: str  # "highlight", "chapter", "intro", "outro"
    text_snippet: str = ""
    is_locked: bool = False
    is_adopted: bool = False
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class SmartCutContext:
    """スマートカットコンテキスト"""
    # 尺設定
    target_duration_minutes: int = 15  # 15, 30, 45, 60
    
    # AI推奨構成
    recommended_segments: List[SegmentCandidate] = field(default_factory=list)
    
    # ユーザー固定シーン
    locked_segments: List[LockedSegment] = field(default_factory=list)
    
    # 全候補（常時閲覧可能）
    all_highlights: List[Dict] = field(default_factory=list)  # 50件
    all_chapters: List[Dict] = field(default_factory=list)    # 30件
    
    # 実際の出力時間
    estimated_output_seconds: float = 0.0
    
    # OP/ED/フェード設定
    opening_duration: float = 10.0
    ending_duration: float = 20.0
    fade_duration: float = 0.5
    fade_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_duration_minutes": self.target_duration_minutes,
            "estimated_output_seconds": self.estimated_output_seconds,
            "estimated_output_str": self._format_time(self.estimated_output_seconds),
            "locked_segments_count": len(self.locked_segments),
            "recommended_segments_count": len(self.recommended_segments),
            "all_highlights_count": len(self.all_highlights),
            "all_chapters_count": len(self.all_chapters),
            "opening_duration": self.opening_duration,
            "ending_duration": self.ending_duration,
        }
    
    def _format_time(self, seconds: float) -> str:
        minutes = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{minutes}:{secs:02d}"


class SmartCutPlugin(Plugin):
    """
    スマートカットプラグイン
    
    PROJECT_CONSTITUTION準拠:
    - §6 議長権限（ユーザーが最終決定）
    - §5.2 Soul Narrative（固定理由を記録）
    - §21 長時間動画対応
    """
    
    name = "smart_cut"
    phase = PluginPhase.POST_PROCESS
    priority = 50
    
    # 尺プリセット
    DURATION_PRESETS = [15, 30, 45, 60]
    
    def __init__(self):
        super().__init__()
        self._context: Optional[SmartCutContext] = None
        self._load_constraints()
    
    def _load_constraints(self):
        """制約条件を読み込み"""
        constraints_path = Path(__file__).parent.parent / "branding" / "video_constraints.json"
        try:
            with open(constraints_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.max_highlight_candidates = config["processing"]["stage1_lightweight"]["highlight_candidates"]
                self.max_chapter_candidates = config["processing"]["stage1_lightweight"]["chapter_candidates"]
        except FileNotFoundError as e:
            logger.warning(f"Constraints file not found: {e}")
            self.max_highlight_candidates = 50
            self.max_chapter_candidates = 30
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in constraints file: {e}")
            self.max_highlight_candidates = 50
            self.max_chapter_candidates = 30
        except PermissionError as e:
            logger.warning(f"Permission denied reading constraints file: {e}")
            self.max_highlight_candidates = 50
            self.max_chapter_candidates = 30
        except Exception as e:
            logger.warning(f"Failed to load constraints: {e}")
            self.max_highlight_candidates = 50
            self.max_chapter_candidates = 30
    
    def can_execute(self, context: ProductionContext) -> bool:
        """スキャン結果が存在する場合に実行"""
        return hasattr(context, 'scan_result') and context.scan_result is not None
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """スマートカット初期化"""
        scan_result = context.scan_result
        
        # SmartCutContextを作成
        self._context = SmartCutContext(
            all_highlights=scan_result.highlight_candidates,
            all_chapters=scan_result.chapter_candidates,
        )
        
        # デフォルト15分で推奨構成を生成
        self.update_recommendation(15)
        
        context.smartcut = self._context
        
        logger.info(f"[SmartCut] Initialized with {len(self._context.all_highlights)} highlights, "
                   f"{len(self._context.all_chapters)} chapters")
        
        return context
    
    def update_recommendation(self, target_minutes: int) -> SmartCutContext:
        """
        尺に応じた推奨構成を生成
        
        Args:
            target_minutes: 目標尺（15, 30, 45, 60）
        """
        mapped_minutes = target_minutes
        if target_minutes not in self.DURATION_PRESETS:
            mapped_minutes = min(self.DURATION_PRESETS, key=lambda x: abs(x - target_minutes))
        
        self._context.target_duration_minutes = mapped_minutes
        
        # 利用可能時間を計算
        locked_duration = sum(s.duration for s in self._context.locked_segments)
        base_overhead = self._context.opening_duration + self._context.ending_duration
        
        # 固定セグメント分のフェードオーバーヘッドを事前に差し引く
        locked_fade_overhead = len(self._context.locked_segments) * self._context.fade_duration
        
        target_seconds = mapped_minutes * 60
        available_seconds = target_seconds - locked_duration - base_overhead - locked_fade_overhead
        
        # 推奨セグメントを選択
        recommended = self._select_segments(available_seconds)
        
        # フェード時間を追加
        fade_count = len(recommended) + len(self._context.locked_segments)
        fade_total = fade_count * self._context.fade_duration
        
        # 実際の出力時間を計算
        content_duration = sum(s.duration for s in recommended) + locked_duration
        total_duration = content_duration + base_overhead + fade_total
        
        # 更新
        self._context.recommended_segments = recommended
        self._context.fade_count = fade_count
        self._context.estimated_output_seconds = total_duration
        
        logger.info(f"[SmartCut] Updated for {target_minutes}min: "
                   f"estimated {total_duration:.0f}s ({total_duration/60:.1f}min)")
        
        return self._context
    
    def _select_segments(self, available_seconds: float, strategy=None) -> List[SegmentCandidate]:
        """
        利用可能時間に収まるセグメントを選択
        
        アルゴリズム:
        1. スコア順にソート（strategy重み適用）
        2. セマンティック境界を考慮してカット調整
        3. 時間内に収まるまで追加
        
        Args:
            available_seconds: 利用可能な秒数
            strategy: CutStrategy (Sprint 4.1.3) — trust_scoreに基づく重み適用
        """
        candidates = []
        used_seconds = 0
        fade_duration = self._context.fade_duration
        
        # ハイライトをスコア順でソート（strategy重みを適用）
        sorted_highlights = sorted(
            self._context.all_highlights,
            key=lambda x: x.get('score', 0) * self._get_strategy_weight(x, strategy),
            reverse=True
        )
        
        for h in sorted_highlights:
            # すでに固定されているセグメントはスキップ
            if any(ls.id == h.get('id') for ls in self._context.locked_segments):
                continue
            
            # セグメント情報を取得
            start = h.get('timestamp', 0)
            duration = h.get('duration', 30)  # デフォルト30秒
            
            # セマンティック境界で調整
            adjusted_duration = self._adjust_to_semantic_boundary(h, duration)
            
            # 推奨セグメント追加に伴うフェード時間も考慮して判定
            next_recommended_fade_total = (len(candidates) + 1) * fade_duration
            if used_seconds + adjusted_duration + next_recommended_fade_total <= available_seconds:
                candidates.append(SegmentCandidate(
                    id=f"seg_{len(candidates):03d}",
                    start_time=start,
                    end_time=start + adjusted_duration,
                    title=h.get('text_snippet', '')[:30],
                    score=h.get('score', 0),
                    type=h.get('type', 'highlight'),
                    text_snippet=h.get('text_snippet', ''),
                    is_adopted=True
                ))
                used_seconds += adjusted_duration
        
        # 時間順にソート（最終的な並び順）
        candidates.sort(key=lambda x: x.start_time)
        
        return candidates

    def _get_strategy_weight(self, highlight: Dict, strategy) -> float:
        """戦略重みを取得（trust_scoreでclamp）

        Sprint 4.1.3: 案Zハイブリッド型
        strategy=None → 1.0（影響なし）
        trust_score=0.0 → 1.0（影響なし）
        trust_score=1.0 → ±22%の範囲でweight適用
        """
        if strategy is None:
            return 1.0
        seg_type = highlight.get('type', 'body')
        raw_weight = strategy.position_weights.get(seg_type, 1.0)
        return self._clamp_weight(raw_weight, strategy.trust_score)

    @staticmethod
    def _clamp_weight(raw_weight: float, trust_score: float) -> float:
        """信頼スコアに基づくweight制約

        trust=0.0 → 常に1.0（影響なし）
        trust=0.7 → ±15%
        trust=1.0 → ±22%
        """
        max_deviation = trust_score * 0.22
        return max(1.0 - max_deviation, min(1.0 + max_deviation, raw_weight))
    
    def _adjust_to_semantic_boundary(self, highlight: Dict, default_duration: float) -> float:
        """
        セマンティック境界でカット位置を調整
        
        - 意味のまとまりを優先
        - ±20%の範囲で調整
        """
        # 簡易実装：±10秒の範囲で調整
        min_duration = default_duration * 0.8
        max_duration = default_duration * 1.2
        
        # ハイライトタイプによる調整
        type_adjustments = {
            "驚き": 1.1,  # 驚きは少し長めに
            "発見": 1.0,
            "転換": 0.9,  # 転換は短めに
            "結論": 1.2,  # 結論は余韻を持たせる
        }
        
        multiplier = type_adjustments.get(highlight.get('type', ''), 1.0)
        adjusted = default_duration * multiplier
        
        return max(min_duration, min(adjusted, max_duration))
    
    def lock_segment(self, segment_id: str, title: str, start: float, end: float, reason: str = "") -> bool:
        """
        シーンを固定
        
        §6 議長権限: ユーザーが「絶対に入れたい」シーンを指定
        §5.2 Soul Narrative: 固定理由をevolution_logに記録
        """
        # すでに固定されていないか確認
        if any(s.id == segment_id for s in self._context.locked_segments):
            return False
        
        locked = LockedSegment(
            id=segment_id,
            start_time=start,
            end_time=end,
            title=title,
            reason=reason
        )
        
        self._context.locked_segments.append(locked)
        
        # 推奨を再計算
        self.update_recommendation(self._context.target_duration_minutes)
        
        # §5.2 Soul Narrative: evolution_logに記録
        self._save_to_evolution_log({
            "event_type": "locked_segment",
            "segment_id": segment_id,
            "title": title,
            "start_time": start,
            "end_time": end,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        
        logger.info(f"[SmartCut] Locked segment: {title} ({start}-{end})")
        
        return True
    
    def _save_to_evolution_log(self, entry: Dict[str, Any]):
        """evolution_logに固定シーン理由を保存"""
        try:
            evolution_path = Path(__file__).parent.parent / "branding" / "evolution_log.json"
            
            if evolution_path.exists():
                with open(evolution_path, 'r', encoding='utf-8') as f:
                    log = json.load(f)
            else:
                log = {"locked_segments": [], "philosophies": []}
            
            if "locked_segments" not in log:
                log["locked_segments"] = []
            
            log["locked_segments"].append(entry)
            
            with open(evolution_path, 'w', encoding='utf-8') as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
                
            logger.info(f"[SmartCut] Saved to evolution_log: {entry['title']}")
            
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in evolution log: {e}")
        except PermissionError as e:
            logger.warning(f"Permission denied writing evolution log: {e}")
        except Exception as e:
            logger.warning(f"Failed to save to evolution_log: {e}")
    
    def unlock_segment(self, segment_id: str) -> bool:
        """固定解除"""
        for i, s in enumerate(self._context.locked_segments):
            if s.id == segment_id:
                self._context.locked_segments.pop(i)
                self.update_recommendation(self._context.target_duration_minutes)
                logger.info(f"[SmartCut] Unlocked segment: {s.title}")
                return True
        return False
    
    def get_all_candidates(self) -> Dict[str, List]:
        """全候補を取得"""
        return {
            "highlights": self._context.all_highlights,
            "chapters": self._context.all_chapters
        }
    
    def get_locked_segments(self) -> List[Dict]:
        """固定シーンを取得"""
        return [
            {
                "id": s.id,
                "title": s.title,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "duration": s.duration,
                "reason": s.reason,
                "locked_at": s.locked_at
            }
            for s in self._context.locked_segments
        ]
    
    def get_recommendation(self) -> Dict[str, Any]:
        """現在の推奨構成を取得"""
        return {
            "target_duration_minutes": self._context.target_duration_minutes,
            "estimated_output_seconds": self._context.estimated_output_seconds,
            "estimated_output_str": self._context._format_time(self._context.estimated_output_seconds),
            "locked_segments": self.get_locked_segments(),
            "recommended_segments": [
                {
                    "id": s.id,
                    "title": s.title,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "duration": s.duration,
                    "score": s.score,
                    "type": s.type,
                    "is_adopted": s.is_adopted
                }
                for s in self._context.recommended_segments
            ],
            "opening_duration": self._context.opening_duration,
            "ending_duration": self._context.ending_duration,
            "fade_count": self._context.fade_count,
        }
    
    def finalize(self) -> Dict[str, Any]:
        """
        最終構成を確定
        
        Soul Narrativeに記録するためのデータを返す
        """
        return {
            "finalized_at": datetime.now().isoformat(),
            "target_duration_minutes": self._context.target_duration_minutes,
            "actual_output_seconds": self._context.estimated_output_seconds,
            "locked_segments": self.get_locked_segments(),
            "adopted_segments_count": len(self._context.recommended_segments),
            "total_candidates_count": len(self._context.all_highlights),
            "cut_rate": 1 - (len(self._context.recommended_segments) / max(len(self._context.all_highlights), 1))
        }

    def run_smart_cut(
        self,
        input_path: str,
        output_path: str,
        threshold: float = 0.04,
        margin: str = "0.2s"
    ) -> bool:
        """WyattBlue/auto-editor を呼び出して、無音区間の自動ジャンプカットを実行する。"""
        from backend.video_pipeline.auto_editor_wrapper import AutoEditorWrapper
        wrapper = AutoEditorWrapper()
        return wrapper.run_smart_cut(
            input_path=input_path,
            output_path=output_path,
            threshold=threshold,
            margin=margin
        )


# シングルトンインスタンス
smart_cut = SmartCutPlugin()


# プラグイン登録用
def register(registry):
    registry.register(SmartCutPlugin())
