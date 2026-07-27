from datetime import datetime, timezone
import re

class CrossMediaService:
    """
    YouTubeと主要SNS（X, Instagram, TikTok, Threads）のクロスメディア相関分析サービス。
    SNSデータのシミュレーションおよびYouTubeアナリティクスとの相関分析を行う。
    """
    def get_default_sns_data(self) -> dict:
        """シミュレーション用のデフォルトSNSデータを生成して返す"""
        return {
            "X": {
                "followers": 12500,
                "posts": [
                    {
                        "text": "最新の自動化スクリプトについての動画を公開しました！ #Python #自動化 #動画制作",
                        "impressions": 4800,
                        "engagement": 380,
                        "posted_at": "2026-05-20T19:15:00"
                    },
                    {
                        "text": "プログラミング効率化のコツを紹介。 #プログラミング #Python",
                        "impressions": 2500,
                        "engagement": 120,
                        "posted_at": "2026-05-19T12:00:00"
                    }
                ]
            },
            "Instagram": {
                "followers": 8400,
                "posts": [
                    {
                        "text": "AIを活用した動画編集パイプラインが完成！ #AI #動画編集 #自動化",
                        "impressions": 3200,
                        "engagement": 450,
                        "posted_at": "2026-05-20T19:30:00"
                    }
                ]
            },
            "TikTok": {
                "followers": 15000,
                "posts": [
                    {
                        "text": "10秒でわかる動画自動化の裏側 #自動化 #Vlog #ショート動画",
                        "impressions": 12000,
                        "engagement": 1500,
                        "posted_at": "2026-05-20T20:00:00"
                    }
                ]
            },
            "Threads": {
                "followers": 3100,
                "posts": [
                    {
                        "text": "Threadsで繋がる開発者コミュニティ。動画公開しました！ #Python #開発",
                        "impressions": 800,
                        "engagement": 45,
                        "posted_at": "2026-05-20T19:05:00"
                    }
                ]
            }
        }

    def _to_naive_utc(self, dt: datetime) -> datetime:
        """datetimeオブジェクトをタイムゾーン情報無しのUTC datetimeに変換する"""
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def _parse_publish_time(self, youtube_analytics: dict) -> datetime:
        """YouTube公開日時をパースし、naive UTC datetimeを返す"""
        pub_time_str = youtube_analytics.get("publish_time")
        try:
            if pub_time_str:
                publish_time = datetime.fromisoformat(pub_time_str)
            else:
                publish_time = datetime.now(timezone.utc)
        except (ValueError, TypeError):
            publish_time = datetime.now(timezone.utc)
        return self._to_naive_utc(publish_time)

    def _parse_posted_at(self, posted_at_str: str) -> datetime:
        """投稿日時をパースし、naive UTC datetimeを返す。エラー時は例外を発生させる"""
        posted_at = datetime.fromisoformat(posted_at_str)
        return self._to_naive_utc(posted_at)

    def _calculate_post_score(self, post: dict) -> float:
        """インプレッションとエンゲージメントの加重和から基礎スコアを計算する"""
        impressions = post.get("impressions", 0)
        engagement = post.get("engagement", 0)
        return impressions * 0.05 + engagement * 1.0

    def _extract_unique_hashtags(self, text: str) -> list:
        """テキストからハッシュタグを抽出し、重複排除してリストで返す"""
        tags = re.findall(r"#\w+", text)
        return list(dict.fromkeys(tags))

    def _calculate_time_decay(self, diff_hours: float) -> float:
        """公開時間との差（時間）から時間減衰率を計算する"""
        return max(0.0, 1.0 - (diff_hours / 24.0))

    def _get_post_diff_hours(self, post: dict, publish_time: datetime) -> float:
        """投稿日時とYouTube公開日時の時間差（絶対値）を計算。パース失敗時は ValueError, TypeError を送出"""
        posted_at_str = post.get("posted_at")
        posted_at = self._parse_posted_at(posted_at_str)
        return abs((posted_at - publish_time).total_seconds()) / 3600.0

    def _calculate_hashtag_contributions(self, text: str, contribution: float, ctr_factor: float) -> dict[str, float]:
        """テキストからハッシュタグを抽出し、それぞれの貢献度を計算する"""
        tags = self._extract_unique_hashtags(text)
        return {tag: contribution * ctr_factor for tag in tags}

    def _process_single_post(
        self, post: dict, publish_time: datetime, ctr_factor: float
    ) -> tuple[float, dict[str, float]]:
        """
        単一の投稿を処理し、その投稿の貢献度スコアとハッシュタグスコアへの寄与分を計算して返す。
        投稿が対象外（24時間超）または日時のパースエラーが発生した場合は (0.0, {}) を返す。
        """
        try:
            diff_hours = self._get_post_diff_hours(post, publish_time)
        except (ValueError, TypeError):
            return 0.0, {}

        if diff_hours > 24.0:
            return 0.0, {}

        post_score = self._calculate_post_score(post)
        decay = self._calculate_time_decay(diff_hours)
        contribution = post_score * decay

        text = post.get("text", "")
        post_hashtag_contributions = self._calculate_hashtag_contributions(text, contribution, ctr_factor)

        return contribution, post_hashtag_contributions

    def _process_sns_data(self, sns_data: dict, publish_time: datetime, youtube_ctr: float) -> tuple[dict, dict]:
        """SNSデータを処理し、プラットフォームごとの貢献度とハッシュタグ相関スコアを計算する"""
        platform_scores = {}
        hashtag_scores = {}
        ctr_factor = youtube_ctr / 10.0

        for platform, platform_info in sns_data.items():
            total_platform_score = 0.0
            posts = platform_info.get("posts", [])
            for post in posts:
                contribution, post_hashtag_contributions = self._process_single_post(
                    post, publish_time, ctr_factor
                )
                total_platform_score += contribution
                for tag, score in post_hashtag_contributions.items():
                    hashtag_scores[tag] = hashtag_scores.get(tag, 0.0) + score

            platform_scores[platform] = round(total_platform_score, 2)

        return platform_scores, hashtag_scores

    def _determine_best_platform(self, platform_scores: dict) -> str:
        """貢献度スコアが最も高い外部流入元プラットフォームを決定する"""
        best_platform = "X"
        max_score = -1.0
        for platform, score in platform_scores.items():
            if score > max_score:
                max_score = score
                best_platform = platform
        return best_platform

    def _determine_suggested_hashtags(self, hashtag_scores: dict) -> list:
        """相関スコアの高い上位3件のハッシュタグを決定し、空の場合はデフォルトを返す"""
        sorted_hashtags = sorted(hashtag_scores.items(), key=lambda item: item[1], reverse=True)
        suggested_hashtags = [tag for tag, score in sorted_hashtags[:3]]
        if not suggested_hashtags:
            suggested_hashtags = ["#動画編集", "#YouTube", "#自動化"]
        return suggested_hashtags

    def _generate_announcement(self, best_platform: str, suggested_hashtags: list) -> str:
        """最適プラットフォームに合わせた告知テキストを生成する"""
        announcement_templates = {
            "X": "【新着動画】YouTubeに新しい動画を公開しました！ぜひご覧ください！ {hashtags} {url}",
            "Instagram": "新しい動画が公開されました！プロフィールリンクからチェックしてください。 {hashtags}",
            "TikTok": "自動化ツールの裏側を公開！フル動画はYouTubeへ。 {hashtags}",
            "Threads": "最新動画を公開！開発の裏側やノウハウを解説しています。 {hashtags} {url}"
        }

        template = announcement_templates.get(best_platform, announcement_templates["X"])
        return template.format(
            hashtags=" ".join(suggested_hashtags),
            url="https://youtu.be/example"
        )

    def analyze_cross_media_correlation(self, youtube_analytics: dict, sns_data: dict = None) -> dict:
        """
        YouTubeのアナリティクスデータとSNSの投稿・インプレッションデータを相関分析する。
        """
        if sns_data is None:
            sns_data = self.get_default_sns_data()

        publish_time = self._parse_publish_time(youtube_analytics)
        youtube_ctr = youtube_analytics.get("ctr", 5.0)

        platform_scores, hashtag_scores = self._process_sns_data(sns_data, publish_time, youtube_ctr)
        best_platform = self._determine_best_platform(platform_scores)
        suggested_hashtags = self._determine_suggested_hashtags(hashtag_scores)
        announcement_text = self._generate_announcement(best_platform, suggested_hashtags)

        return {
            "platform_contribution": {
                "best_platform": best_platform,
                "contribution_scores": platform_scores
            },
            "hashtag_correlation": {tag: round(score, 2) for tag, score in hashtag_scores.items()},
            "optimized_announcement": {
                "text": announcement_text,
                "suggested_hashtags": suggested_hashtags
            }
        }
