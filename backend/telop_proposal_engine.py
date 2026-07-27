"""
テロップ提案エンジン
Phase 3: Generative Proposal

機能:
- Semantic Storeからテロップ候補を抽出
- 重要度に基づくランキング
- スタイル提案
- シーン構成提案
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

from dotenv import load_dotenv
from gemini_client_factory import get_gemini_client
import os
from google.api_core.exceptions import GoogleAPIError

from model_registry import get_model

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class TelopCandidate:
    """テロップ候補"""
    id: str
    segment_id: str
    start: float
    end: float
    original_text: str
    telop_text: str
    importance: float
    style_suggestion: str = "default"
    position_suggestion: str = "bottom_center"
    duration_sec: float = 3.0
    reason: str = ""


@dataclass
class SceneProposal:
    """シーン構成提案"""
    id: str
    name: str
    start_time: float
    end_time: float
    duration_sec: float
    telop_count: int
    summary: str = ""
    mood: str = "neutral"


class TelopProposalEngine:
    """テロップ提案エンジン"""
    
    TELOP_PROMPT = """
以下の字幕セグメントから、テロップにすべき重要な発言を抽出してください。

## セグメント
{segments}

## 基準
- 名言・格言的な発言
- 視聴者の記憶に残る印象的なフレーズ
- 話のポイント・結論
- 数字・固有名詞を含む重要情報

## 出力形式（JSON）
{{
  "telop_candidates": [
    {{
      "segment_id": "seg_001",
      "telop_text": "短縮テロップ（20文字以内）",
      "importance": 0.9,
      "style_suggestion": "emphasis",
      "position_suggestion": "center",
      "reason": "名言"
    }},
    ...
  ]
}}

テロップは最大10件まで抽出してください。
"""

    SCENE_PROMPT = """
以下の字幕とトピック情報から、動画のシーン構成を提案してください。

## セグメント
{segments}

## トピック
{topics}

## 出力形式（JSON）
{{
  "scenes": [
    {{
      "name": "オープニング",
      "start_seg": "seg_001",
      "end_seg": "seg_005",
      "summary": "自己紹介と番組説明",
      "mood": "welcoming",
      "suggested_telops": 2
    }},
    ...
  ]
}}
"""

    def __init__(self):
        self.client = get_gemini_client()
        self.model = get_model("quality_gate")
    
    def extract_telop_candidates(self, segments: List[Dict], max_candidates: int = 10) -> List[TelopCandidate]:
        """
        セグメントからテロップ候補を抽出
        
        Args:
            segments: 正規化されたセグメントリスト
            max_candidates: 最大候補数
        
        Returns:
            テロップ候補リスト
        """
        # セグメントをテキスト化
        segments_text = "\n".join([
            f"[{s.get('id', f'seg_{i:03d}')}] ({s.get('start', 0):.1f}s) {s.get('text', '')}"
            for i, s in enumerate(segments)
        ])
        
        prompt = self.TELOP_PROMPT.format(segments=segments_text)
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            candidates = self._parse_telop_response(response.text, segments)
        except GoogleAPIError as e:
            logger.error(f"テロップ抽出APIエラー (GoogleAPIError): {e}")
            candidates = self._fallback_extract(segments)
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.exception(f"テロップ抽出パースまたはパラメータエラー: {e}")
            candidates = self._fallback_extract(segments)
        
        # 重要度でソートして上位を返す
        candidates.sort(key=lambda x: x.importance, reverse=True)
        return candidates[:max_candidates]
    
    def _parse_telop_response(self, text: str, segments: List[Dict]) -> List[TelopCandidate]:
        """AIレスポンスをパース"""
        import re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            return self._fallback_extract(segments)
        
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return self._fallback_extract(segments)
        
        candidates = []
        seg_map = {s.get('id', f"seg_{i:03d}"): s for i, s in enumerate(segments)}
        
        for i, c in enumerate(data.get("telop_candidates", [])):
            seg_id = c.get("segment_id", "")
            seg = seg_map.get(seg_id, {})
            
            candidates.append(TelopCandidate(
                id=f"telop_{i:03d}",
                segment_id=seg_id,
                start=seg.get("start", 0),
                end=seg.get("end", 0),
                original_text=seg.get("text", ""),
                telop_text=c.get("telop_text", ""),
                importance=c.get("importance", 0.5),
                style_suggestion=c.get("style_suggestion", "default"),
                position_suggestion=c.get("position_suggestion", "bottom_center"),
                reason=c.get("reason", "")
            ))
        
        return candidates
    
    def _fallback_extract(self, segments: List[Dict]) -> List[TelopCandidate]:
        """フォールバック抽出（ルールベース）"""
        candidates = []
        keywords = ["大切", "本質", "秘訣", "ポイント", "重要", "核心", "すごい", "感動"]
        
        for i, seg in enumerate(segments):
            text = seg.get("text", "")
            seg_id = seg.get("id", f"seg_{i:03d}")
            
            # キーワードマッチング
            if any(kw in text for kw in keywords) and len(text) < 50:
                candidates.append(TelopCandidate(
                    id=f"telop_{len(candidates):03d}",
                    segment_id=seg_id,
                    start=seg.get("start", 0),
                    end=seg.get("end", 0),
                    original_text=text,
                    telop_text=text[:20] if len(text) > 20 else text,
                    importance=0.7,
                    reason="キーワードマッチ"
                ))
        
        return candidates
    
    def propose_scene_structure(self, segments: List[Dict], topics: List[Dict] = None) -> List[SceneProposal]:
        """
        シーン構成を提案
        
        Args:
            segments: セグメントリスト
            topics: トピックリスト（オプション）
        
        Returns:
            シーン提案リスト
        """
        segments_text = "\n".join([
            f"[{s.get('id', f'seg_{i:03d}')}] ({s.get('start', 0):.1f}s) {s.get('text', '')[:50]}"
            for i, s in enumerate(segments[:50])  # 最初の50セグメント
        ])
        
        topics_text = json.dumps(topics or [], ensure_ascii=False)
        
        prompt = self.SCENE_PROMPT.format(
            segments=segments_text,
            topics=topics_text
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            scenes = self._parse_scene_response(response.text, segments)
        except GoogleAPIError as e:
            logger.error(f"シーン提案APIエラー (GoogleAPIError): {e}")
            scenes = self._fallback_scene_proposal(segments)
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.exception(f"シーン提案パースまたはパラメータエラー: {e}")
            scenes = self._fallback_scene_proposal(segments)
        
        return scenes
    
    def _parse_scene_response(self, text: str, segments: List[Dict]) -> List[SceneProposal]:
        """シーン提案レスポンスをパース"""
        import re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            return self._fallback_scene_proposal(segments)
        
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return self._fallback_scene_proposal(segments)
        
        proposals = []
        seg_map = {s.get('id', f"seg_{i:03d}"): s for i, s in enumerate(segments)}
        
        for i, scene in enumerate(data.get("scenes", [])):
            start_seg = seg_map.get(scene.get("start_seg", ""), {})
            end_seg = seg_map.get(scene.get("end_seg", ""), {})
            
            start_time = start_seg.get("start", 0)
            end_time = end_seg.get("end", 0)
            
            proposals.append(SceneProposal(
                id=f"scene_{i:02d}",
                name=scene.get("name", f"シーン{i+1}"),
                start_time=start_time,
                end_time=end_time,
                duration_sec=end_time - start_time,
                telop_count=scene.get("suggested_telops", 0),
                summary=scene.get("summary", ""),
                mood=scene.get("mood", "neutral")
            ))
        
        return proposals
    
    def _fallback_scene_proposal(self, segments: List[Dict]) -> List[SceneProposal]:
        """フォールバックシーン提案"""
        total_segments = len(segments)
        if total_segments == 0:
            return []
            
        # 均等分割
        # セグメント数が非常に少ない場合は分割数を制限
        scenes_count = min(5, max(1, total_segments // 50))
        if total_segments < 2:
            scenes_count = 1
            
        segments_per_scene = total_segments // scenes_count
        
        proposals = []
        for i in range(scenes_count):
            start_idx = i * segments_per_scene
            end_idx = min((i + 1) * segments_per_scene - 1, total_segments - 1)
            
            start_seg = segments[start_idx]
            end_seg = segments[end_idx]
            
            proposals.append(SceneProposal(
                id=f"scene_{i:02d}",
                name=f"パート{i+1}",
                start_time=start_seg.get("start", 0),
                end_time=end_seg.get("end", 0),
                duration_sec=end_seg.get("end", 0) - start_seg.get("start", 0),
                telop_count=2
            ))
        
        return proposals
    
    def generate_proposal_report(self, 
                                  telop_candidates: List[TelopCandidate],
                                  scene_proposals: List[SceneProposal]) -> Dict:
        """提案レポートを生成"""
        return {
            "generated_at": datetime.now().isoformat(),
            "telop_candidates": [asdict(t) for t in telop_candidates],
            "scene_proposals": [asdict(s) for s in scene_proposals],
            "summary": {
                "total_telops": len(telop_candidates),
                "total_scenes": len(scene_proposals),
                "avg_telop_importance": sum(t.importance for t in telop_candidates) / len(telop_candidates) if telop_candidates else 0
            }
        }


# シングルトンインスタンス
telop_engine = TelopProposalEngine()


def extract_telops(segments: List[Dict], max_candidates: int = 10) -> List[Dict]:
    """テロップ候補を抽出（簡易関数）"""
    candidates = telop_engine.extract_telop_candidates(segments, max_candidates)
    return [asdict(c) for c in candidates]


def propose_scenes(segments: List[Dict]) -> List[Dict]:
    """シーン構成を提案（簡易関数）"""
    proposals = telop_engine.propose_scene_structure(segments)
    return [asdict(p) for p in proposals]
