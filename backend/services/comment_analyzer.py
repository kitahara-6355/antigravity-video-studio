"""
コメント分析サービス（BIZ-7）

視聴者エンゲージメント分析:
- コメントのセンチメント分析
- リクエスト抽出（「次の動画で○○やって」等）
- 視聴者期待のトレンド分析
"""
import json
import logging
import re
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "branding"
COMMENTS_FILE = DATA_DIR / "comment_analysis.json"


class CommentAnalyzer:
    """コメント分析"""

    # リクエストパターン（日本語）
    REQUEST_PATTERNS = [
        r"((?:次[はの]?|今度[はの]?).*(?:やって|して|作って|出して|紹介して|教えて|お願い))",
        r"(.*(?:動画|企画|コラボ).*(?:見たい|希望|リクエスト|待ってます))",
        r"(.*(?:もっと|また).*(?:見たい|やって|して))",
    ]

    # ポジティブキーワード
    POSITIVE_WORDS = [
        "面白い", "最高", "神", "好き", "わかりやすい", "ためになる",
        "参考になる", "素晴らしい", "感動", "笑った", "楽しい",
        "すごい", "天才", "上手い", "推し", "ありがとう",
    ]

    # ネガティブキーワード
    NEGATIVE_WORDS = [
        "つまらない", "長い", "わからない", "見にくい", "うるさい",
        "広告", "雑", "手抜き", "微妙", "残念", "改善",
    ]

    def analyze_comments(self, comments: List[str], video_id: str = "") -> Dict[str, Any]:
        """コメント一覧を分析"""
        # ガード処理
        if comments is None:
            return {"success": False, "message": "コメントが空です"}
        if not isinstance(comments, (list, tuple)):
            return {"success": False, "message": "無効な入力データです"}
        if not comments:
            return {"success": False, "message": "コメントが空です"}

        # video_id のガード
        if not isinstance(video_id, str):
            video_id = str(video_id) if video_id is not None else ""

        # コメントのクレンジング（None は除外し、文字列以外は文字列化、最大1000文字に切り詰め）
        cleaned_comments = []
        for comment in comments:
            if comment is None:
                continue
            if not isinstance(comment, str):
                comment_str = str(comment)
            else:
                comment_str = comment
            
            # 最大1000文字に制限して正規表現のパフォーマンスを保護
            if len(comment_str) > 1000:
                comment_str = comment_str[:1000]
            cleaned_comments.append(comment_str)

        if not cleaned_comments:
            return {"success": False, "message": "コメントが空です"}

        sentiments = {"positive": 0, "neutral": 0, "negative": 0}
        requests = []
        keyword_counts = {}

        for comment in cleaned_comments:
            # センチメント分析
            sentiment = self._classify_sentiment(comment)
            sentiments[sentiment] += 1

            # リクエスト抽出
            extracted = self._extract_requests(comment)
            requests.extend(extracted)

            # キーワード頻度
            for word in self._extract_keywords(comment):
                keyword_counts[word] = keyword_counts.get(word, 0) + 1

        total = len(cleaned_comments)
        positivity_rate = round(sentiments["positive"] / total * 100, 1) if total else 0

        # 上位キーワード
        top_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        result = {
            "success": True,
            "video_id": video_id,
            "total_comments": total,
            "sentiment": {
                "positive": sentiments["positive"],
                "neutral": sentiments["neutral"],
                "negative": sentiments["negative"],
                "positivity_rate": positivity_rate,
                "assessment": (
                    "🟢 高評価" if positivity_rate >= 70
                    else "🟡 普通" if positivity_rate >= 40
                    else "🔴 改善要"
                ),
            },
            "viewer_requests": requests[:10],
            "top_keywords": [{"word": w, "count": c} for w, c in top_keywords],
            "actionable_insights": self._generate_insights(sentiments, requests, top_keywords),
        }

        # 結果を保存
        self._save_analysis(result)

        return result

    def _classify_sentiment(self, comment: str) -> str:
        """センチメント分類"""
        if not isinstance(comment, str):
            comment = str(comment) if comment is not None else ""
        pos_score = sum(1 for w in self.POSITIVE_WORDS if w in comment)
        neg_score = sum(1 for w in self.NEGATIVE_WORDS if w in comment)

        if pos_score > neg_score:
            return "positive"
        elif neg_score > pos_score:
            return "negative"
        return "neutral"

    def _extract_requests(self, comment: str) -> List[str]:
        """リクエストコメントを抽出"""
        if not isinstance(comment, str):
            comment = str(comment) if comment is not None else ""
        requests = []
        for pattern in self.REQUEST_PATTERNS:
            matches = re.findall(pattern, comment)
            for m in matches:
                if isinstance(m, str):
                    cleaned = m.strip()
                elif isinstance(m, (list, tuple)) and len(m) > 0:
                    cleaned = m[0].strip()
                else:
                    cleaned = str(m).strip()
                if len(cleaned) > 5:
                    requests.append(cleaned)
        return requests

    def _extract_keywords(self, comment: str) -> List[str]:
        """主要キーワードを抽出"""
        if not isinstance(comment, str):
            comment = str(comment) if comment is not None else ""
        found = []
        for w in self.POSITIVE_WORDS + self.NEGATIVE_WORDS:
            if w in comment:
                found.append(w)
        return found

    def _generate_insights(self, sentiments: Dict, requests: List, keywords: List) -> List[str]:
        """アクション可能なインサイトを生成"""
        insights = []
        total = sum(sentiments.values())
        if total == 0:
            return ["コメント数が不足しています。"]

        pos_rate = sentiments["positive"] / total
        neg_rate = sentiments["negative"] / total

        if pos_rate >= 0.7:
            insights.append("✅ 視聴者満足度が高い。現在のスタイルを維持してください。")
        elif neg_rate >= 0.3:
            insights.append("⚠️ ネガティブコメントが30%以上。内容の改善を検討してください。")

        if len(requests) >= 3:
            insights.append(f"📝 視聴者リクエスト{len(requests)}件。次回企画の参考にしてください。")

        if not insights:
            insights.append("💡 コメント分析結果は中立的です。トピックの訴求力を強化してみてください。")

        return insights

    def _save_analysis(self, result: Dict):
        """分析結果を保存"""
        try:
            # 親ディレクトリの存在保証ガード
            COMMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            data = []
            if COMMENTS_FILE.exists():
                try:
                    data = json.loads(COMMENTS_FILE.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        data = []
                except json.JSONDecodeError:
                    data = []
            data.append({
                "timestamp": datetime.now().isoformat(),
                **result,
            })
            # 最新30件を保持
            if len(data) > 30:
                data = data[-30:]

            # アトミック書き込みの実行
            tmp_fd = None
            tmp_path = None
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=str(COMMENTS_FILE.parent), suffix=".tmp", prefix="comments_tmp_"
                )
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, str(COMMENTS_FILE))
            except (OSError, TypeError, ValueError) as write_err:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                logger.error(f"コメント分析ファイル書き込み失敗: {write_err}")
                raise
        except (OSError, TypeError, ValueError, AttributeError) as e:
            logger.warning(f"コメント分析保存失敗: {e}")

    def get_request_trends(self) -> Dict[str, Any]:
        """過去のリクエストトレンドを集計"""
        try:
            if not COMMENTS_FILE.exists():
                return {"success": False, "message": "分析データがありません"}

            try:
                data = json.loads(COMMENTS_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    return {"success": False, "message": "分析データの形式が不正です"}
            except json.JSONDecodeError as jde:
                return {"success": False, "message": f"分析データが破損しています: {jde}"}

            all_requests = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                all_requests.extend(entry.get("viewer_requests", []))

            return {
                "success": True,
                "total_requests": len(all_requests),
                "unique_requests": list(set(all_requests))[:20],
                "analysis_count": len(data),
            }
        except (OSError, TypeError, ValueError, AttributeError) as e:
            logger.error(f"リクエストトレンド集計中にエラーが発生しました: {e}")
            return {"success": False, "message": str(e)}


comment_analyzer = CommentAnalyzer()
