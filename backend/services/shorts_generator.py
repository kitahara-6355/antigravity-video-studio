\
"""
ショート動画量産サービス（BIZ-3）

本編動画からYouTube Shorts向けコンテンツを自動生成:
- ハイライトセグメント抽出
- 縦長リフォーマット仕様生成
- Shorts向けテロップ仕様（巨大文字・画面中央）
- 本編への誘導CTA生成
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ShortsGenerator:
    """Shorts自動量産"""

    MAX_DURATION = 60  # 秒
    ASPECT_RATIO = "9:16"
    RESOLUTION = "1080x1920"

    def extract_shorts_candidates(
        self,
        segments: List[Dict[str, Any]],
        video_duration_sec: int,
        video_id: str = "",
    ) -> Dict[str, Any]:
        """本編セグメントからShorts候補を抽出"""

        candidates = []

        if not segments or video_duration_sec <= 0:
            return {
                "success": True,
                "video_id": video_id,
                "total_candidates": 0,
                "candidates": [],
                "shorts_spec": {
                    "aspect_ratio": self.ASPECT_RATIO,
                    "resolution": self.RESOLUTION,
                    "max_duration_sec": self.MAX_DURATION,
                    "subtitle_style": "巨大文字・画面中央・太字白文字・黒縁取り",
                },
                "cta_templates": self._generate_cta_templates(video_id),
            }

        # 戦略1: フック部分（冒頭5-15秒）
        hook_segments = []
        for s in segments:
            start_val = s.get("start")
            if start_val is not None and start_val < 15:
                hook_segments.append(s)

        if hook_segments:
            candidates.append(self._build_candidate(
                video_id=video_id, strategy="hook_clip",
                title="冒頭フック切り出し", segments=hook_segments,
                start=0.0, end=min(15.0, float(video_duration_sec)), priority=1,
            ))

        # 戦略2: ハイライトセグメント
        for i, seg in enumerate(segments):
            text = seg.get("text") or ""
            if any(w in text for w in ["！", "!?", "すごい", "やばい", "衝撃", "最高"]):
                seg_start = seg.get("start")
                start = max(0.0, (seg_start - 3.0) if seg_start is not None else 0.0)
                if start >= video_duration_sec:
                    continue
                seg_end = seg.get("end")
                end = min(seg_end if seg_end is not None else (start + 30.0), start + self.MAX_DURATION)
                end = min(end, float(video_duration_sec))
                if end <= start:
                    continue
                candidates.append(self._build_candidate(
                    video_id=video_id, strategy="highlight",
                    title=f"ハイライト #{i+1}", segments=[seg],
                    start=start, end=end, priority=2,
                ))

        # 戦略3: まとめ・結論部分（終盤20%）
        end_threshold = video_duration_sec * 0.8
        conclusion_segments = []
        for s in segments:
            start_val = s.get("start")
            if start_val is not None and start_val >= end_threshold:
                conclusion_segments.append(s)

        if conclusion_segments:
            seg_start = conclusion_segments[0].get("start")
            start = seg_start if seg_start is not None else end_threshold
            start = min(start, float(video_duration_sec))
            end = min(start + 45.0, float(video_duration_sec))
            if end > start:
                candidates.append(self._build_candidate(
                    video_id=video_id, strategy="conclusion",
                    title="まとめ・結論クリップ", segments=conclusion_segments[:3],
                    start=start, end=end, priority=3,
                ))

        candidates.sort(key=lambda c: c["priority"])
        candidates = candidates[:5]

        return {
            "success": True,
            "video_id": video_id,
            "total_candidates": len(candidates),
            "candidates": candidates,
            "shorts_spec": {
                "aspect_ratio": self.ASPECT_RATIO,
                "resolution": self.RESOLUTION,
                "max_duration_sec": self.MAX_DURATION,
                "subtitle_style": "巨大文字・画面中央・太字白文字・黒縁取り",
            },
            "cta_templates": self._generate_cta_templates(video_id),
        }

    def _build_candidate(self, video_id, strategy, title, segments, start, end, priority):
        duration = round(end - start, 1)
        texts = [s.get("text", "") for s in segments if s.get("text")]
        return {
            "id": f"shorts_{video_id}_{strategy}_{int(start)}",
            "strategy": strategy,
            "title": title,
            "start_sec": round(start, 1),
            "end_sec": round(end, 1),
            "duration_sec": duration,
            "priority": priority,
            "preview_text": " ".join(texts)[:100],
            "reformat_spec": {
                "crop": "center_crop_9x16",
                "subtitle_position": "center",
                "subtitle_size": "48px",
                "subtitle_style": "bold_white_black_outline",
            },
            "estimated_views_boost": self._estimate_boost(strategy),
        }

    def _generate_cta_templates(self, video_id):
        return [
            {"type": "end_card", "text": "フル動画はプロフィールから！", "timing": "last_3_seconds"},
            {"type": "pinned_comment", "text": "この動画の完全版はこちら → [本編リンク]"},
            {"type": "description", "text": "#Shorts #切り抜き\nフル動画→ [本編リンク]"},
        ]

    def _estimate_boost(self, strategy):
        boosts = {
            "hook_clip": "本編比 3-5x の発見性向上",
            "highlight": "高エンゲージメント → チャンネル登録誘導",
            "conclusion": "価値提供 → 本編視聴への誘導",
        }
        return boosts.get(strategy, "チャンネル発見性向上")


shorts_generator = ShortsGenerator()
