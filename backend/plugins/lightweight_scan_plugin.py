"""
LightweightScanPlugin - 軽量スキャンプラグイン（Stage 1）

長時間動画対応ベストプラクティス準拠:
- RAW動画全体（最大3時間）を高速スキャン
- ハイライト候補50件、チャプター候補30件を抽出
- 深層分析前の前処理として機能
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
import json
from pathlib import Path

import re

from core.plugin import Plugin, PluginPhase
from core.context import ProductionContext

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """軽量スキャン結果"""
    total_segments: int
    total_duration_seconds: float
    highlight_candidates: List[Dict[str, Any]]
    chapter_candidates: List[Dict[str, Any]]
    topic_summary: List[str]
    estimated_cut_rate: float  # 推定カット率
    processing_time_seconds: float


class LightweightScanPlugin(Plugin):
    """
    Stage 1: 軽量スキャンプラグイン
    
    PROJECT_CONSTITUTION準拠:
    - §16 プラグインアーキテクチャ
    - §5.2 Soul Narrative（スキャン結果を記録）
    """
    
    name = "lightweight_scan"
    phase = PluginPhase.PRE_PROCESS
    priority = 10  # 最初に実行
    
    def __init__(self):
        super().__init__()
        self._load_constraints()
    
    def _load_constraints(self):
        """制約条件を読み込み"""
        constraints_path = Path(__file__).parent.parent / "branding" / "video_constraints.json"
        try:
            with open(constraints_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.max_segments = int(config["processing"]["stage1_lightweight"]["max_segments"])
                self.highlight_limit = int(config["processing"]["stage1_lightweight"]["highlight_candidates"])
                self.chapter_limit = int(config["processing"]["stage1_lightweight"]["chapter_candidates"])
                if self.max_segments < 0 or self.highlight_limit < 0 or self.chapter_limit < 0:
                    raise ValueError("Constraints must be non-negative integers")
        except FileNotFoundError as e:
            logger.warning(f"Constraints file not found at {constraints_path}, using defaults: {e}")
            self._set_default_constraints()
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON format in constraints file, using defaults: {e}")
            self._set_default_constraints()
        except KeyError as e:
            logger.warning(f"Missing required key in constraints file, using defaults: {e}")
            self._set_default_constraints()
        except (TypeError, ValueError) as e:
            logger.warning(f"Invalid value type or range in constraints file, using defaults: {e}")
            self._set_default_constraints()
        except OSError as e:
            logger.warning(f"Unexpected OS error loading constraints, using defaults: {e}")
            self._set_default_constraints()

    def _set_default_constraints(self):
        self.max_segments = 6000
        self.highlight_limit = 50
        self.chapter_limit = 30
    
    def can_execute(self, context: ProductionContext) -> bool:
        """セグメントが存在する場合に実行"""
        return hasattr(context, 'segments') and len(context.segments) > 0
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """軽量スキャンを実行"""
        start_time = datetime.now()
        
        try:
            if not context:
                raise ValueError("ProductionContext is None")
            
            segments = getattr(context, 'segments', None)
            if segments is None:
                logger.warning("Context has no segments attribute. Setting empty scan result.")
                segments = []
            elif not isinstance(segments, list):
                logger.warning(f"Context segments is not a list (got {type(segments)}). Setting empty scan result.")
                segments = []
            
            # 各セグメントが辞書型であることを確認し、型を補正して安全なリストを構成
            safe_segments = []
            for i, seg in enumerate(segments):
                if not isinstance(seg, dict):
                    logger.warning(f"Segment at index {i} is not a dict (got {type(seg)}). Skipping.")
                    continue
                
                safe_seg = {
                    "text": str(seg.get("text", "")),
                    "start": 0.0,
                    "end": 0.0
                }
                
                try:
                    safe_seg["start"] = float(seg.get("start", 0.0))
                except (TypeError, ValueError):
                    logger.warning(f"Invalid start value at segment {i}, fallback to 0.0")
                
                try:
                    safe_seg["end"] = float(seg.get("end", 0.0))
                except (TypeError, ValueError):
                    logger.warning(f"Invalid end value at segment {i}, fallback to 0.0")
                
                safe_segments.append(safe_seg)
            
            sliced_segments = safe_segments[:self.max_segments]
            total_duration = sliced_segments[-1].get("end", 0.0) if sliced_segments else 0.0
            
            logger.info(f"[Stage 1] Lightweight scan started: {len(sliced_segments)} segments, {total_duration:.1f}s")
            
            # 各処理を安全に実行
            highlight_candidates = self._extract_highlight_candidates(sliced_segments)
            chapter_candidates = self._extract_chapter_candidates(sliced_segments)
            topic_summary = self._generate_topic_summary(sliced_segments)
            estimated_cut_rate = self._estimate_cut_rate(total_duration)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # 結果をコンテキストに保存
            context.scan_result = ScanResult(
                total_segments=len(sliced_segments),
                total_duration_seconds=total_duration,
                highlight_candidates=highlight_candidates,
                chapter_candidates=chapter_candidates,
                topic_summary=topic_summary,
                estimated_cut_rate=estimated_cut_rate,
                processing_time_seconds=processing_time
            )
            
            logger.info(f"[Stage 1] Scan complete: {len(highlight_candidates)} highlights, "
                        f"{len(chapter_candidates)} chapters, {processing_time:.2f}s")
            
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as e:
            logger.error(f"Critical error in Stage 1 lightweight scan: {e}", exc_info=True)
            if not context:
                raise
            processing_time = (datetime.now() - start_time).total_seconds()
            context.scan_result = ScanResult(
                total_segments=0,
                total_duration_seconds=0.0,
                highlight_candidates=[],
                chapter_candidates=[],
                topic_summary=[],
                estimated_cut_rate=0.0,
                processing_time_seconds=processing_time
            )
        
        return context
    
    def _extract_highlight_candidates(self, segments: List[Dict]) -> List[Dict[str, Any]]:
        """ハイライト候補を抽出"""
        candidates = []
        
        # 感情キーワードと重み
        emotion_patterns = {
            "驚き": {"keywords": ["すごい", "驚き", "衝撃", "まさか", "信じられない", "!"], "weight": 20},
            "発見": {"keywords": ["実は", "秘密", "コツ", "ポイント", "重要"], "weight": 18},
            "転換": {"keywords": ["しかし", "ところが", "実際は", "ここで"], "weight": 15},
            "結論": {"keywords": ["つまり", "結局", "まとめると", "要するに"], "weight": 17},
            "質問": {"keywords": ["?", "？", "なぜ", "どうして"], "weight": 16},
            "数値": {"keywords": ["10", "100", "倍", "億"], "weight": 14}
        }
        
        for i, seg in enumerate(segments):
            text = seg.get("text", "")
            start = seg.get("start", 0)
            
            for emotion_type, config in emotion_patterns.items():
                for keyword in config["keywords"]:
                    if keyword in text:
                        candidates.append({
                            "segment_index": i,
                            "timestamp": start,
                            "type": emotion_type,
                            "keyword": keyword,
                            "text_snippet": text[:60],
                            "score": config["weight"],
                            "adopted": None  # Stage 2で決定
                        })
                        break
        
        # スコア順でソートし、上位を返す
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:self.highlight_limit]
    
    def _extract_chapter_candidates(self, segments: List[Dict]) -> List[Dict[str, Any]]:
        """チャプター候補を抽出"""
        candidates = []
        
        topic_markers = [
            "次に", "まず", "最初に", "続いて", "ここで", "では",
            "ポイント", "重要", "注意", "ところで", "さて",
            "まとめ", "結論", "最後に", "つまり", "第一に", "第二に"
        ]
        
        # 常にオープニングを追加
        candidates.append({
            "timestamp": 0,
            "title": "オープニング",
            "marker": None,
            "adopted": True  # オープニングは常に採用
        })
        
        total_duration = segments[-1].get("end", 0) if segments else 0
        min_interval = max(30, total_duration / 40)  # 最低30秒間隔
        last_time = 0
        
        for seg in segments:
            text = seg.get("text", "")
            start = seg.get("start", 0)
            
            if start - last_time < min_interval:
                continue
            
            for marker in topic_markers:
                if marker in text:
                    minutes = int(start) // 60
                    seconds = int(start) % 60
                    
                    # タイトルを抽出
                    idx = text.find(marker)
                    title_snippet = text[idx:idx+20].replace(marker, "").strip()[:15] or marker
                    
                    candidates.append({
                        "timestamp": start,
                        "time_str": f"{minutes}:{seconds:02d}",
                        "title": title_snippet,
                        "marker": marker,
                        "adopted": None  # Stage 2で決定
                    })
                    last_time = start
                    break
        
        return candidates[:self.chapter_limit]
    
    def _generate_topic_summary(self, segments: List[Dict]) -> List[str]:
        """トピック要約を生成"""
        # 簡易的なキーワード抽出
        all_text = " ".join(seg.get("text", "") for seg in segments)
        
        # 頻出キーワードを抽出（実際はGeminiで処理）
        keywords = []
        common_words = ["の", "を", "に", "が", "は", "で", "と", "も", "から", "まで"]
        
        # 名詞っぽい文字列を抽出（簡易版）
        for seg in segments[:100]:  # 先頭100セグメントから抽出
            text = seg.get("text", "")
            # 日本語・英数字簡易トークナイズ（漢字、カタカナ、英数字の連続を抽出）
            words = re.findall(r"[一-龠]+|[ァ-ヴー]+|[a-zA-Z0-9_]+", text)
            if not words:
                words = text.split()
            
            for word in words:
                if len(word) >= 2 and word not in common_words and word not in keywords:
                    keywords.append(word)
                    if len(keywords) >= 10:
                        break
            if len(keywords) >= 10:
                break
        
        return keywords[:10]
    
    def _estimate_cut_rate(self, total_duration: float) -> float:
        """推定カット率を計算"""
        if not isinstance(total_duration, (int, float)):
            raise TypeError(f"total_duration must be int or float, got {type(total_duration).__name__}")
        if total_duration < 0:
            raise ValueError(f"total_duration must be non-negative, got {total_duration}")

        # 1時間（3600秒）が目標投稿長
        target_duration = 3600
        
        if total_duration <= target_duration:
            return 0.0
        
        return (total_duration - target_duration) / total_duration * 100


# プラグイン登録用
def register(registry):
    registry.register(LightweightScanPlugin())
