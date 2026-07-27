"""
template_recommender.py — テンプレート自動推奨AI

素材の音声特性（テンポ・ダイナミクス・発話密度・無音率）を分析し、
最適なテンプレートを初心者向けに自動推奨する。

初心者ファーストUX:
  「おまかせ」ボタンを押すだけで最適テンプレートが選ばれる。
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class TemplateRecommender:
    """
    素材分析に基づくテンプレート自動推奨エンジン。

    分析指標:
      1. 発話密度（segments/minute）
      2. 平均無音区間（秒）
      3. 平均セグメント長（文字数）
      4. テンポ（短いセグメントの割合）
    """

    # テンプレートIDとプロファイルのマッピング
    TEMPLATE_PROFILES = {
        "nhk_documentary": {
            "speech_density_range": (3, 12),     # 発話/分: ゆったり
            "avg_silence_range": (2.0, 10.0),    # 間が多い
            "avg_segment_chars_range": (15, 50),  # 長めの文
            "tempo_fast_ratio_max": 0.3,          # 速いテンポは少ない
            "priority": 3,                        # 優先度（低い=より特化的）
        },
        "mrbeast_entertainment": {
            "speech_density_range": (15, 40),    # 高密度
            "avg_silence_range": (0.2, 1.5),     # ほぼ無音なし
            "avg_segment_chars_range": (5, 25),   # 短い発話
            "tempo_fast_ratio_max": 1.0,          # 速いテンポOK
            "priority": 2,
        },
        "hikakin_vlog": {
            "speech_density_range": (8, 25),     # 中程度
            "avg_silence_range": (0.5, 3.0),     # 適度な間
            "avg_segment_chars_range": (8, 35),   # 中程度の文
            "tempo_fast_ratio_max": 0.7,
            "priority": 4,                        # デフォルト（汎用性高い）
        },
        "asmr_relaxation": {
            "speech_density_range": (1, 8),      # 低密度
            "avg_silence_range": (3.0, 30.0),    # 長い沈黙OK
            "avg_segment_chars_range": (5, 20),   # 短いささやき
            "tempo_fast_ratio_max": 0.15,         # ほぼスロー
            "priority": 1,                        # 最も特化的
        },
    }

    def _clean_segments(self, segments: List[Dict]) -> List[Dict]:
        """
        セグメントリストの各要素をクレンジングし、型安全な辞書のリストを返す。
        """
        cleaned = []
        for s in segments:
            if not isinstance(s, dict):
                continue
            text = s.get("text", "")
            if text is None:
                text = ""
            elif not isinstance(text, str):
                text = str(text)

            start = s.get("start", 0)
            try:
                start = float(start) if start is not None else 0.0
            except (ValueError, TypeError):
                start = 0.0

            end = s.get("end", 0)
            try:
                end = float(end) if end is not None else 0.0
            except (ValueError, TypeError):
                end = 0.0

            cleaned.append({"start": start, "end": end, "text": text})
        return cleaned

    def analyze_segments(self, segments: List[Dict],
                         total_duration_seconds: float = 0) -> Dict:
        """
        セグメントデータから素材プロファイルを算出。

        Args:
            segments: [{text, start, end}, ...]
            total_duration_seconds: 動画全体の長さ（0の場合は最終セグメントから推定）

        Returns:
            {speech_density, avg_silence, avg_segment_chars, tempo_fast_ratio}
        """
        if not segments:
            return {
                "speech_density": 0,
                "avg_silence": 0,
                "avg_segment_chars": 0,
                "tempo_fast_ratio": 0,
            }

        cleaned_segments = self._clean_segments(segments)

        if not cleaned_segments:
            return {
                "speech_density": 0,
                "avg_silence": 0,
                "avg_segment_chars": 0,
                "tempo_fast_ratio": 0,
            }

        # 総再生時間の算出と検証
        try:
            total_duration_seconds = float(total_duration_seconds)
        except (ValueError, TypeError):
            total_duration_seconds = 0.0

        if total_duration_seconds <= 0:
            total_duration_seconds = max(
                s.get("end", 0) for s in cleaned_segments
            )

        total_minutes = max(total_duration_seconds / 60, 0.1)

        # 1. 発話密度（segments / minute）
        speech_density = len(cleaned_segments) / total_minutes

        # 2. 平均無音区間
        silences = []
        for i in range(1, len(cleaned_segments)):
            gap = cleaned_segments[i].get("start", 0) - cleaned_segments[i - 1].get("end", 0)
            if gap > 0:
                silences.append(gap)
        avg_silence = sum(silences) / len(silences) if silences else 0

        # 3. 平均セグメント文字数
        char_counts = [len(s.get("text", "")) for s in cleaned_segments]
        avg_segment_chars = sum(char_counts) / len(char_counts) if char_counts else 0

        # 4. テンポ（2秒以下の短いセグメントの割合）
        short_segments = sum(
            1 for s in cleaned_segments
            if 0 <= (s.get("end", 0) - s.get("start", 0)) < 2.0
        )
        tempo_fast_ratio = short_segments / max(len(cleaned_segments), 1)

        return {
            "speech_density": round(speech_density, 1),
            "avg_silence": round(avg_silence, 2),
            "avg_segment_chars": round(avg_segment_chars, 1),
            "tempo_fast_ratio": round(tempo_fast_ratio, 2),
        }

    def _score_speech_density(self, density: float, min_val: float, max_val: float) -> Tuple[float, Optional[str]]:
        """発話密度のスコアとマッチング理由を計算する。"""
        if min_val <= density <= max_val:
            return 30.0, f"発話密度 {density}/分 が範囲内"
        elif density < min_val:
            score = max(0.0, 30.0 - (min_val - density) * 3)
            return score, None
        else:
            score = max(0.0, 30.0 - (density - max_val) * 2)
            return score, None

    def _score_silence(self, avg_silence: float, min_val: float, max_val: float) -> Tuple[float, Optional[str]]:
        """平均無音区間のスコアとマッチング理由を計算する。"""
        if min_val <= avg_silence <= max_val:
            return 25.0, f"無音間隔 {avg_silence}秒 が範囲内"
        elif avg_silence < min_val:
            score = max(0.0, 25.0 - (min_val - avg_silence) * 5)
            return score, None
        else:
            score = max(0.0, 25.0 - (avg_silence - max_val) * 3)
            return score, None

    def _score_segment_chars(self, avg_chars: float, min_val: float, max_val: float) -> Tuple[float, Optional[str]]:
        """平均セグメント文字数のスコアとマッチング理由を計算する。"""
        if min_val <= avg_chars <= max_val:
            return 25.0, f"平均文字数 {avg_chars}文字 が範囲内"
        return 0.0, None

    def _score_tempo(self, tempo_ratio: float, max_val: float) -> Tuple[float, Optional[str]]:
        """テンポ比率のスコアとマッチング理由を計算する。"""
        if tempo_ratio <= max_val:
            return 20.0, f"テンポ比率 {tempo_ratio} が基準内"
        return 0.0, None

    def _calculate_scores(self, segments: List[Dict],
                          total_duration_seconds: float = 0) -> Tuple[str, Dict]:
        """
        全テンプレートのスコアを算出して学習バイアスを適用。
        recommend と recommend_with_alternatives の共通ロジック。
        """
        profile = self.analyze_segments(segments, total_duration_seconds)
        scores = {}

        for tmpl_id, tmpl_profile in self.TEMPLATE_PROFILES.items():
            score = 0.0
            reasons = []

            # 発話密度マッチング
            sd_min, sd_max = tmpl_profile["speech_density_range"]
            sd_score, sd_reason = self._score_speech_density(profile["speech_density"], sd_min, sd_max)
            score += sd_score
            if sd_reason:
                reasons.append(sd_reason)

            # 無音区間マッチング
            sl_min, sl_max = tmpl_profile["avg_silence_range"]
            sl_score, sl_reason = self._score_silence(profile["avg_silence"], sl_min, sl_max)
            score += sl_score
            if sl_reason:
                reasons.append(sl_reason)

            # セグメント文字数マッチング
            sc_min, sc_max = tmpl_profile["avg_segment_chars_range"]
            sc_score, sc_reason = self._score_segment_chars(profile["avg_segment_chars"], sc_min, sc_max)
            score += sc_score
            if sc_reason:
                reasons.append(sc_reason)

            # テンポマッチング
            tempo_score, tempo_reason = self._score_tempo(profile["tempo_fast_ratio"], tmpl_profile["tempo_fast_ratio_max"])
            score += tempo_score
            if tempo_reason:
                reasons.append(tempo_reason)

            scores[tmpl_id] = {
                "score": round(score, 1),
                "reasons": reasons,
                "profile": profile,
            }

        # 最高スコアのテンプレートを選択（同点ならpriority高い方）
        best_id = max(
            scores,
            key=lambda k: (
                scores[k]["score"],
                self.TEMPLATE_PROFILES[k]["priority"]
            )
        )

        # 学習ループ: evolution_logの選択履歴でスコア補正
        best_id = self._apply_learning_bias(best_id, scores)

        return best_id, scores

    def recommend(self, segments: List[Dict],
                  total_duration_seconds: float = 0) -> Tuple[str, Dict]:
        """
        最適テンプレートを推奨。

        Returns:
            (template_id, {"score": float, "reasons": [str], "profile": dict})
        """
        best_id, scores = self._calculate_scores(segments, total_duration_seconds)
        logger.info(
            f"🤖 テンプレート推奨: {best_id} "
            f"(スコア: {scores[best_id]['score']})"
        )
        return best_id, scores[best_id]

    def _apply_learning_bias(self, best_id: str, scores: Dict) -> str:
        """
        evolution_log.json の選択履歴から学習バイアスを適用。
        
        憲法§5.2「哲学の深化」に準拠:
          制作を重ねるごとに、ユーザーの嗜好が推奨に反映される。
          
        ロジック:
          - 過去に選択→高評価されたテンプレートにボーナス（+15）
          - 過去に選択→低評価されたテンプレートにペナルティ（-10）
          - 選択回数が多いテンプレートに馴染みボーナス（+5）
        """
        try:
            evolution_log_paths = [
                Path(__file__).parent / "branding" / "evolution_log.json",
                Path("backend/branding/evolution_log.json"),
            ]
            
            history = []
            for path in evolution_log_paths:
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        history = data.get("template_selections", [])
                        if not isinstance(history, list):
                            history = []
                    break
            
            if not history:
                return best_id
            
            # テンプレート別の選択回数と満足度平均を集計
            selection_stats = {}
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                tid = entry.get("template_id", "")
                if not isinstance(tid, str) or not tid:
                    continue

                satisfaction = entry.get("satisfaction")
                try:
                    if satisfaction is None:
                        satisfaction = 3
                    else:
                        satisfaction = int(satisfaction)
                        if not (1 <= satisfaction <= 5):
                            satisfaction = 3
                except (ValueError, TypeError):
                    satisfaction = 3

                if tid not in selection_stats:
                    selection_stats[tid] = {"count": 0, "total_sat": 0}
                selection_stats[tid]["count"] += 1
                selection_stats[tid]["total_sat"] += satisfaction
            
            # スコアにバイアスを適用
            for tid in scores:
                if tid in selection_stats:
                    stats = selection_stats[tid]
                    avg_sat = stats["total_sat"] / stats["count"]
                    
                    # 馴染みボーナス（選択回数）
                    scores[tid]["score"] += min(5, stats["count"])
                    
                    # 満足度バイアス
                    if avg_sat >= 4:
                        scores[tid]["score"] += 15
                        scores[tid]["reasons"].append(
                            f"📈 過去{stats['count']}回選択・高評価（平均{avg_sat:.1f}）")
                    elif avg_sat <= 2:
                        scores[tid]["score"] -= 10
                        scores[tid]["reasons"].append(
                            f"📉 過去に低評価（平均{avg_sat:.1f}）")
            
            # 再ソート
            return max(
                scores,
                key=lambda k: (
                    scores[k]["score"],
                    self.TEMPLATE_PROFILES[k]["priority"]
                )
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse evolution_log.json: {e}")
            return best_id
        except OSError as e:
            logger.warning(f"Failed to read evolution_log.json: {e}")
            return best_id
        except (KeyError, TypeError) as e:
            logger.warning(f"Invalid structure in evolution_log.json: {e}")
            return best_id
        except Exception as e:
            logger.error(f"Unexpected error in apply_learning_bias: {e}")
            return best_id

    def recommend_with_alternatives(self, segments: List[Dict],
                                     total_duration_seconds: float = 0
                                     ) -> List[Dict]:
        """
        推奨テンプレートと代替案を優先度付きで返す。
        フロントエンドの「おまかせ」UI用。
        """
        best_id, scores = self._calculate_scores(segments, total_duration_seconds)

        # スコア順にソート（最高スコアを先頭に、同点ならpriority順）
        sorted_ids = sorted(
            scores,
            key=lambda k: (
                scores[k]["score"],
                self.TEMPLATE_PROFILES[k]["priority"]
            ),
            reverse=True
        )

        return [
            {
                "template_id": tid,
                "score": scores[tid]["score"],
                "is_recommended": tid == best_id,
            }
            for tid in sorted_ids
        ]


# シングルトン
template_recommender = TemplateRecommender()
"""テンプレート自動推奨エンジン（学習ループ搭載）"""
