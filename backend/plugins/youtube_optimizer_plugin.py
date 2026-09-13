"""
YouTube Optimized Context - YouTube成長特化コンテキスト

youtube_expert_review.md 提言に基づく拡張:
- hook_score: 冒頭5秒のフック評価
- thumbnail_candidates: A/Bテスト用複数パターン（3案）
- seo_metadata: タイトル案、タグ、チャプター、説明文
- viewer_persona_fit: ターゲット視聴者適合度
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import json
import logging
import re

# Model resolution via unified governance gateway
try:
    from model_governance import model_governance as _mg
    def _resolve_model(task): return _mg._resolve_model(task)
except ImportError:
    def _resolve_model(task): return "gemini-3.6-flash"

logger = logging.getLogger(__name__)


@dataclass
class HookAnalysis:
    """冒頭フック分析結果"""
    score: float                      # 0-100: フックの強さ
    attention_grabber: str            # 「驚き」「疑問」「約束」等
    first_5_seconds_text: str         # 冒頭5秒のテキスト
    improvement_suggestions: List[str] # 改善提案
    predicted_retention_impact: str   # 予測される視聴維持率への影響


@dataclass
class ThumbnailCandidate:
    """サムネイル候補"""
    id: str
    path: Optional[Path] = None
    image_data: Optional[str] = None  # base64
    concept: str = ""                  # コンセプト説明
    target_emotion: str = ""           # 狙う感情（好奇心、驚き等）
    text_overlay: str = ""             # テキストオーバーレイ案
    predicted_ctr: float = 0.0         # 予測CTR（%）
    ctr_confidence: str = ""           # CTR信頼区間（例: "3.5% - 5.5%"）
    ctr_factors: List[str] = field(default_factory=list)  # CTR計算根拠
    

@dataclass
class SEOMetadata:
    """SEOメタデータ"""
    title_candidates: List[str]        # タイトル案（3-5案）
    description: str                   # 説明文（5000文字以内）
    tags: List[str]                    # タグ（最大500文字分）
    hashtags: List[str]                # ハッシュタグ（最大3つ推奨）
    chapters: List[Dict[str, Any]]     # チャプター情報
    category: str                      # カテゴリ
    keywords: List[str]                # 主要キーワード


@dataclass 
class YouTubeOptimizedContext:
    """
    YouTuberサポート専門家が求める拡張コンテキスト
    
    youtube_expert_review.md 提言準拠:
    - CTR向上: サムネイル3案 + タイトル案
    - リテンション向上: フック分析 + ハイライト自動特定
    - ブランド一貫性: Soul Narrative強制反映
    - 生産性: バッチ処理対応
    """
    # === 基本情報 ===
    task_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # === フック分析（冒頭5秒）===
    hook_analysis: Optional[HookAnalysis] = None
    hook_score: float = 0.0  # 簡易アクセス用
    
    # === A/Bテスト用サムネイル ===
    thumbnail_candidates: List[ThumbnailCandidate] = field(default_factory=list)
    selected_thumbnail_id: Optional[str] = None
    
    # === SEOメタデータ ===
    seo_metadata: Optional[SEOMetadata] = None
    
    # === 視聴者適合度 ===
    viewer_persona_fit: float = 0.0  # 0-100
    target_persona: Optional[str] = None
    
    # === ハイライト（盛り上がり山場）===
    highlights: List[Dict[str, Any]] = field(default_factory=list)
    
    # === Soul Narrative統合 ===
    soul_narrative: Optional[str] = None
    brand_consistency_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "task_id": self.task_id,
            "created_at": self.created_at,
            "hook_score": self.hook_score,
            "hook_analysis": self.hook_analysis.__dict__ if self.hook_analysis else None,
            "thumbnail_candidates": [
                {
                    "id": t.id,
                    "concept": t.concept,
                    "target_emotion": t.target_emotion,
                    "text_overlay": t.text_overlay,
                    "predicted_ctr": t.predicted_ctr
                }
                for t in self.thumbnail_candidates
            ],
            "selected_thumbnail_id": self.selected_thumbnail_id,
            "seo_metadata": self.seo_metadata.__dict__ if self.seo_metadata else None,
            "viewer_persona_fit": self.viewer_persona_fit,
            "target_persona": self.target_persona,
            "highlights_count": len(self.highlights),
            "soul_narrative": self.soul_narrative,
            "brand_consistency_score": self.brand_consistency_score
        }


class YouTubeOptimizerPlugin:
    """
    YouTube最適化プラグイン
    
    提言3項目を実装:
    1. フック分析（冒頭5秒）
    2. サムネイル3案生成（A/Bテスト対応）
    3. SEOメタデータ生成
    """
    
    name = "youtube_optimizer"
    
    def __init__(self):
        self._model = _resolve_model("branding")  # Standard tier for batch processing
        
    async def analyze_hook(self, segments: List[Dict]) -> HookAnalysis:
        """
        冒頭5秒のフック分析
        
        youtube_expert_review.md 提言:
        「冒頭5秒のフック」の自動構成機能
        """
        # 冒頭5秒のセグメントを抽出
        first_5_seconds = []
        for seg in segments:
            end_time = seg.get("end", 0)
            if end_time <= 5.0:
                first_5_seconds.append(seg)
            elif seg.get("start", 0) < 5.0:
                first_5_seconds.append(seg)
                break
        
        first_5_text = " ".join(s.get("text", "") for s in first_5_seconds)
        
        # フック強度を評価
        score, attention_type, suggestions = self._evaluate_hook(first_5_text)
        
        return HookAnalysis(
            score=score,
            attention_grabber=attention_type,
            first_5_seconds_text=first_5_text,
            improvement_suggestions=suggestions,
            predicted_retention_impact=self._predict_retention_impact(score)
        )
    
    def _evaluate_hook(self, text: str, genre: str = "general") -> tuple:
        """
        フックを評価（プロ基準: 10種類のタイプ分類、ジャンル別最適化）
        
        youtube_uiux_expert_review.md 改善要件:
        - タイプ分類: 4種類 → 10種類
        - ジャンル別最適化
        - 感情分析AI活用
        """
        score = 0.0
        attention_types = []
        suggestions = []
        
        # 10種類のフックタイプ評価
        hook_patterns = {
            "question": {"patterns": ["?", "？", "なぜ", "どうして", "知っていますか"], "weight": 15},
            "specificity": {"patterns": [r"\d+"], "weight": 12, "regex": True},
            "surprise": {"patterns": ["!", "！", "驚き", "衝撃", "まさか"], "weight": 10},
            "promise": {"patterns": ["わかる", "できる", "なれる", "教えます"], "weight": 12},
            "controversy": {"patterns": ["実は", "本当は", "嘘", "間違い"], "weight": 14},
            "urgency": {"patterns": ["今すぐ", "急いで", "限定", "最後の"], "weight": 8},
            "story": {"patterns": ["私は", "ある日", "昔", "経験"], "weight": 10},
            "benefit": {"patterns": ["得する", "損しない", "節約", "無料"], "weight": 11},
            "fear": {"patterns": ["危険", "注意", "やめて", "失敗"], "weight": 9},
            "authority": {"patterns": ["プロ", "専門家", "年間", "経験者"], "weight": 10}
        }
        
        for hook_type, config in hook_patterns.items():
            for pattern in config["patterns"]:
                if config.get("regex"):
                    if re.search(pattern, text):
                        score += config["weight"]
                        attention_types.append(hook_type)
                        break
                else:
                    if pattern in text:
                        score += config["weight"]
                        attention_types.append(hook_type)
                        break
        
        # ジャンル別ボーナス
        genre_bonus = {
            "education": {"specificity": 5, "promise": 5, "authority": 5},
            "entertainment": {"surprise": 5, "story": 5, "controversy": 5},
            "business": {"benefit": 5, "authority": 5, "specificity": 5}
        }
        
        if genre in genre_bonus:
            for t in attention_types:
                if t in genre_bonus[genre]:
                    score += genre_bonus[genre][t]
        
        # 主要タイプを決定（複数ある場合は最も効果的なもの）
        primary_type = attention_types[0] if attention_types else "neutral"
        
        # 改善提案（ジャンル別）
        if score < 70:
            if genre == "education":
                suggestions.extend([
                    "具体的な数字（例: 3つのポイント）を冒頭に入れましょう",
                    "「これを見れば〇〇がわかる」という明確な約束を入れましょう",
                    "専門家としての権威性を示しましょう"
                ])
            elif genre == "entertainment":
                suggestions.extend([
                    "驚きや意外性のある言葉で始めましょう",
                    "個人的なストーリーで引き込みましょう",
                    "常識を覆す発言で興味を引きましょう"
                ])
            else:
                suggestions.extend([
                    "冒頭に具体的な数字や結果を入れましょう",
                    "視聴者への問いかけで興味を引きましょう",
                    "「これを見れば〇〇がわかる」という約束を入れましょう"
                ])
        
        return min(score, 100), primary_type, suggestions
    
    def _predict_retention_impact(self, score: float) -> str:
        """視聴維持率への影響を予測"""
        if score >= 80:
            return "高: 冒頭離脱率が低く、視聴維持率向上が期待できます"
        elif score >= 60:
            return "中: 一定の引きはありますが、改善の余地があります"
        else:
            return "低: 冒頭離脱リスクが高く、フック強化を推奨します"
            
    @staticmethod
    def calculate_dynamic_ctr(query: str) -> float:
        """
        タイトル文字列のヒューリスティックに基づくCTR予測。
        感嘆符・疑問符・文字数・パワーワードでスコアを計算する。
        
        ※蒸留知識（knowledge_base）を利用した補正は呼び出し元（Analyst.process）が担う。
          このメソッドは純粋なテキスト分析のみを行い、副作用なしで値を返す。
        """
        import warnings
        warnings.warn(
            "calculate_dynamic_ctr is deprecated and will be removed in a future version. "
            "Use calculate_video_ctr instead.",
            category=DeprecationWarning,
            stacklevel=2
        )
        return YouTubeOptimizerPlugin.calculate_video_ctr(query)

    @staticmethod
    def calculate_video_ctr(query: str) -> float:
        """
        タイトル文字列のヒューリスティックに基づくCTR予測。
        感嘆符・疑問符・文字数・パワーワードでスコアを計算する。
        
        ※蒸留知識（knowledge_base）を利用した補正は呼び出し元（Analyst.process）が担う。
          このメソッドは純粋なテキスト分析のみを行い、副作用なしで値を返す。
        """
        base_ctr = 3.5
        
        if "!" in query or "！" in query:
            base_ctr += 0.8
        if "?" in query or "？" in query:
            base_ctr += 0.5
            
        # 文字数がYouTubeのタイトル適正値 (15-35文字) に近いか
        length = len(query)
        if 15 <= length <= 35:
            base_ctr += 1.2
        elif length < 10:
            base_ctr -= 1.0
            
        # パワーワード
        power_words = ["完全版", "徹底解説", "真実", "裏技", "保存版", "衝撃"]
        for pw in power_words:
            if pw in query:
                base_ctr += 1.5
                break
                
        return round(max(0.5, min(15.0, base_ctr)), 1)

    
    async def generate_thumbnail_candidates(
        self,
        context: Dict[str, Any],
        count: int = 3
    ) -> List[ThumbnailCandidate]:
        """
        A/Bテスト用サムネイル候補を生成
        
        youtube_expert_review.md 提言:
        「3パターンのサムネイル案とその意図」を生成
        """
        candidates = []
        
        # 3つの異なるコンセプトを定義
        concepts = [
            {
                "id": "curiosity",
                "concept": "好奇心喚起型",
                "target_emotion": "好奇心",
                "text_pattern": "「〇〇の真実」「知らないと損する〇〇」",
                "predicted_ctr": 8.5
            },
            {
                "id": "surprise",
                "concept": "驚き・インパクト型",
                "target_emotion": "驚き",
                "text_pattern": "「衝撃」「まさかの結果」",
                "predicted_ctr": 7.8
            },
            {
                "id": "benefit",
                "concept": "ベネフィット訴求型",
                "target_emotion": "期待",
                "text_pattern": "「〇〇する方法」「簡単〇〇」",
                "predicted_ctr": 7.2
            }
        ]
        
        topic = context.get("topic", "")
        
        for i, concept in enumerate(concepts[:count]):
            candidates.append(ThumbnailCandidate(
                id=f"thumb_{concept['id']}_{i+1}",
                concept=concept["concept"],
                target_emotion=concept["target_emotion"],
                text_overlay=f"{topic}の{concept['text_pattern'].split('「')[1].split('」')[0]}",
                predicted_ctr=concept["predicted_ctr"]
            ))
        
        return candidates
    
    async def generate_seo_metadata(
        self,
        segments: List[Dict],
        topics: List[str],
        context: Dict[str, Any]
    ) -> SEOMetadata:
        """
        SEOメタデータを生成
        
        youtube_expert_review.md 提言:
        「動画タイトル候補」と「説明文/ハッシュタグ」の生成
        """
        full_text = " ".join(s.get("text", "") for s in segments)
        main_topic = topics[0] if topics else "動画"
        
        # タイトル候補を生成
        title_candidates = [
            f"【完全版】{main_topic}を徹底解説",
            f"{main_topic}の真実｜プロが教える裏技",
            f"知らないと損する{main_topic}の話",
            f"【保存版】{main_topic}マスター講座",
            f"{main_topic}で人生が変わった話"
        ]
        
        # 説明文を生成
        description = self._generate_description(main_topic, topics, full_text[:500])
        
        # タグを抽出（プロ基準: 15-20個）
        tags = self._generate_expanded_tags(main_topic, topics, full_text)
        
        # ハッシュタグ（最大3つ）
        hashtags = [f"#{main_topic}", "#解説動画", "#必見"]
        
        # チャプターを生成
        chapters = self._generate_chapters(segments)
        
        return SEOMetadata(
            title_candidates=title_candidates,
            description=description,
            tags=tags,
            hashtags=hashtags[:3],
            chapters=chapters,
            category="教育" if "解説" in full_text else "エンターテイメント",
            keywords=topics[:5]
        )
    
    async def generate_pre_edit_assets(self, concept: str) -> Dict[str, Any]:
        """
        Phase 1: Title-First Pipeline
        企画段階（事前編集）で、入力されたコンセプトに基づいてタイトルとサムネイル案を生成する。
        """
        # 1. 5 Titles
        title_candidates = [
            f"【完全版】{concept}を徹底解説",
            f"{concept}の真実｜プロが教える裏技",
            f"知らないと損する{concept}の話",
            f"【保存版】{concept}マスター講座",
            f"{concept}で人生が変わった話"
        ]
        
        # 2. 3 Thumbnails
        thumbnails = await self.generate_thumbnail_candidates({"topic": concept}, count=3)
        
        return {
            "title_candidates": title_candidates,
            "thumbnails": [t.__dict__ for t in thumbnails]
        }
        
    def _generate_description(self, main_topic: str, topics: List[str], snippet: str) -> str:
        """説明文を生成"""
        lines = [
            f"この動画では「{main_topic}」について詳しく解説します。",
            "",
            "【この動画でわかること】",
        ]
        
        for i, topic in enumerate(topics[:5], 1):
            lines.append(f"✅ {topic}")
        
        lines.extend([
            "",
            "【チャンネル登録はこちら】",
            "👉 [チャンネルURL]",
            "",
            "【関連動画】",
            "▶ [関連動画タイトル]",
            "",
            f"#動画 #{main_topic} #解説"
        ])
        
        return "\n".join(lines)
    
    def _generate_chapters(self, segments: List[Dict]) -> List[Dict[str, Any]]:
        """
        チャプターを自動生成（プロ基準: トピック境界で5-10個）
        
        youtube_uiux_expert_review.md 改善要件:
        - 2個 → 動画長に応じて5-10個
        - セマンティック分析と連携
        """
        if not segments:
            return []
        
        total_duration = segments[-1].get("end", 0) if segments else 0
        
        # 1. トピック境界マーカーによるチャプター生成
        chapters = self._detect_topic_boundary_chapters(segments, total_duration)
        
        # 2. 最低5チャプターを保証（均等分割で補完）
        if len(chapters) < 5 and total_duration >= 60:
            chapters = self._fallback_equal_chapters(total_duration)
        
        return chapters

    def _detect_topic_boundary_chapters(self, segments: List[Dict], total_duration: float) -> List[Dict[str, Any]]:
        """トピック境界マーカーを検出してチャプターを生成"""
        chapters = []
        
        # トピック境界を検出するキーワード
        topic_markers = [
            "次に", "まず", "最初に", "続いて", "ここで", "では",
            "ポイント", "重要", "注意", "ところで", "さて",
            "まとめ", "結論", "最後に", "つまり"
        ]
        
        # 常にオープニングから開始
        chapters.append({"time": "0:00", "title": "オープニング"})
        
        chapter_count = 1
        last_chapter_time = 0
        min_interval = max(30.0, total_duration / 12.0)  # 最低30秒または動画の1/12
        
        for seg in segments:
            text = seg.get("text", "")
            start = seg.get("start", 0)
            
            # 前回のチャプターから十分な間隔があるか
            if start - last_chapter_time < min_interval:
                continue
            
            # トピックマーカーを検出
            for marker in topic_markers:
                if marker in text and chapter_count < 10:
                    minutes = int(start) // 60
                    seconds = int(start) % 60
                    
                    # チャプタータイトルを生成
                    title = self._extract_chapter_title(text, marker)
                    
                    chapters.append({
                        "time": f"{minutes}:{seconds:02d}",
                        "title": title
                    })
                    chapter_count += 1
                    last_chapter_time = start
                    break
                    
        return chapters

    def _fallback_equal_chapters(self, total_duration: float) -> List[Dict[str, Any]]:
        """均等分割によるフォールバックチャプターを生成"""
        interval = total_duration / 5
        default_titles = ["オープニング", "導入", "本題", "詳細解説", "まとめ"]
        chapters = []
        for i, title in enumerate(default_titles):
            time_sec = int(i * interval)
            minutes = time_sec // 60
            seconds = time_sec % 60
            chapters.append({"time": f"{minutes}:{seconds:02d}", "title": title})
        return chapters
    
    def _extract_chapter_title(self, text: str, marker: str) -> str:
        """テキストからチャプタータイトルを抽出"""
        # マーカーの後の10文字を抽出してタイトル化
        idx = text.find(marker)
        if idx >= 0:
            snippet = text[idx:idx+15].replace(marker, "").strip()
            if snippet:
                return snippet[:10]
        return marker
    
    def _generate_expanded_tags(self, main_topic: str, topics: List[str], full_text: str) -> List[str]:
        """
        タグを拡充生成（プロ基準: 15-20個）
        
        youtube_uiux_expert_review.md 改善要件:
        - 6個 → 15-20個
        """
        tags = []
        
        # 1. メイントピックとバリエーション
        tags.append(main_topic)
        tags.append(f"{main_topic}解説")
        tags.append(f"{main_topic}入門")
        tags.append(f"{main_topic}初心者")
        
        # 2. サブトピック
        for topic in topics[:5]:
            if topic != main_topic:
                tags.append(topic)
        
        # 3. 一般的なYouTube SEOタグ
        general_tags = [
            "解説", "講座", "初心者向け", "わかりやすい",
            "徹底解説", "保存版", "完全版", "やり方"
        ]
        tags.extend(general_tags)
        
        # 4. 年度タグ
        from datetime import datetime
        year = datetime.now().year
        tags.append(f"{year}年")
        tags.append(f"{year}年版")
        
        # 重複を削除し、15-20個に調整
        tags = list(dict.fromkeys(tags))[:20]
        
        return tags
    
    async def optimize_context(
        self,
        segments: List[Dict],
        topics: List[str],
        context: Dict[str, Any]
    ) -> YouTubeOptimizedContext:
        """
        YouTube最適化コンテキストを生成
        
        全提言項目を統合実行
        """
        yt_context = YouTubeOptimizedContext(
            task_id=context.get("task_id", f"yt_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        )
        
        # 1. フック分析
        logger.info("Analyzing hook (first 5 seconds)...")
        hook = await self.analyze_hook(segments)
        yt_context.hook_analysis = hook
        yt_context.hook_score = hook.score
        
        # 2. サムネイル候補生成 (Imagen 4.0統合)
        logger.info("Generating thumbnail candidates (3 patterns)...")
        thumbnails = await self.generate_thumbnail_candidates(context)
        yt_context.thumbnail_candidates = thumbnails
        
        # 3. SEOメタデータ生成
        logger.info("Generating SEO metadata...")
        seo = await self.generate_seo_metadata(segments, topics, context)
        yt_context.seo_metadata = seo
        
        # 4. ハイライト自動特定（強化版）
        logger.info("Detecting highlights (peak moments)...")
        yt_context.highlights = await self.detect_highlights(segments, topics)
        
        # 5. Director Brain連携
        logger.info("Integrating with Director Brain...")
        await self._integrate_director_brain(yt_context, context)
        
        # 6. Soul Narrative統合
        yt_context.soul_narrative = context.get("soul_narrative", 
            "「視聴者の時間を無駄にしない」という信念のもと、価値ある情報を届ける")
        
        # 7. 動的CTR予測計算
        logger.info("Calculating dynamic CTR predictions...")
        await self._apply_dynamic_ctr_to_thumbnails(yt_context, context)
        
        logger.info(f"YouTube optimization complete. Hook score: {yt_context.hook_score}")
        
        return yt_context
    
    async def detect_highlights(
        self,
        segments: List[Dict],
        topics: List[str]
    ) -> List[Dict[str, Any]]:
        """
        ハイライト（盛り上がりの山場）を自動特定
        
        youtube_expert_review.md 提言:
        「盛り上がりの山場（ハイライト）を自動特定する機能の強化」
        """
        highlights = []
        
        # 感情的なキーワードを検出
        emotion_keywords = {
            "驚き": ["すごい", "驚き", "衝撃", "まさか", "信じられない", "!"],
            "発見": ["実は", "秘密", "コツ", "ポイント", "重要"],
            "転換": ["しかし", "ところが", "実際は", "ここで"],
            "結論": ["つまり", "結局", "まとめると", "要するに"]
        }
        
        for i, seg in enumerate(segments):
            text = seg.get("text", "")
            start = seg.get("start", 0)
            
            for emotion_type, keywords in emotion_keywords.items():
                for keyword in keywords:
                    if keyword in text:
                        highlights.append({
                            "segment_index": i,
                            "timestamp": start,
                            "type": emotion_type,
                            "keyword": keyword,
                            "text_snippet": text[:50],
                            "importance": self._calculate_importance(text, topics)
                        })
                        break
        
        # 重要度でソートし、上位5件を返す
        highlights.sort(key=lambda x: x.get("importance", 0), reverse=True)
        return highlights[:5]
    
    def _calculate_importance(self, text: str, topics: List[str]) -> float:
        """重要度を計算"""
        score = 0.0
        
        # トピックとの関連度
        for topic in topics:
            if topic in text:
                score += 30
        
        # 数字を含む（具体性）
        if re.search(r'\d+', text):
            score += 20
        
        # 感嘆符（強調）
        score += text.count("!") * 5 + text.count("！") * 5
        
        # 疑問形（視聴者の興味を引く）
        if "?" in text or "？" in text:
            score += 15
        
        return min(score, 100)
    
    async def _integrate_director_brain(
        self,
        yt_context: YouTubeOptimizedContext,
        context: Dict[str, Any]
    ) -> None:
        """
        Director Brainとの連携
        
        youtube_expert_review.md 提言:
        「Director Brainとの連携で明示されていない」問題を解決
        """
        try:
            # Director Brainからスタイル分析を取得
            from director_engine import brain
            
            # フック分析結果をDirector Brainに反映
            if yt_context.hook_analysis:
                hook_feedback = {
                    "hook_score": yt_context.hook_score,
                    "attention_type": yt_context.hook_analysis.attention_grabber,
                    "suggestions": yt_context.hook_analysis.improvement_suggestions
                }
                
                # Director Brainの次回提案に反映
                context["director_brain_feedback"] = hook_feedback
                
                # Soul Narrativeに強制反映
                if yt_context.hook_score < 70 and yt_context.soul_narrative:
                    yt_context.soul_narrative += "（フック強化が課題）"
            
            # ハイライトをDirector Brainに連携
            if yt_context.highlights:
                context["detected_highlights"] = yt_context.highlights
            
            logger.info("Director Brain integration complete")
            
        except ImportError:
            logger.warning("Director Brain not available, skipping integration")
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Director Brain integration failed due to data structure mismatch: {e}")
    
    async def _apply_dynamic_ctr_to_thumbnails(
        self,
        yt_context: YouTubeOptimizedContext,
        context: Dict[str, Any]
    ) -> None:
        """
        動的CTR予測
        
        静的値ではなく、コンテキストに基づいて動的に計算
        """
        # プロ基準: 業界平均2-5%をベースライン
        base_ctr = 3.0  # 業界平均（中央値）
        
        for thumbnail in yt_context.thumbnail_candidates:
            ctr = base_ctr
            ctr_factors = []  # CTR計算根拠を記録
            
            # フックスコアによる補正
            hook_bonus, hook_factor = self._get_hook_ctr_modifier(yt_context.hook_score)
            ctr += hook_bonus
            ctr_factors.append(hook_factor)
            
            # SEOメタデータの質による補正
            seo_bonuses = self._get_seo_ctr_modifiers(yt_context.seo_metadata)
            for bonus, factor in seo_bonuses:
                ctr += bonus
                ctr_factors.append(factor)
            
            # ハイライト数による補正
            highlight_bonus, highlight_factor = self._get_highlights_ctr_modifier(len(yt_context.highlights))
            ctr += highlight_bonus
            if highlight_factor:
                ctr_factors.append(highlight_factor)
            
            # ターゲット感情による補正
            emotion_bonus, emotion_factor = self._get_emotion_ctr_modifier(thumbnail.target_emotion)
            ctr += emotion_bonus
            if emotion_factor:
                ctr_factors.append(emotion_factor)
            
            # CTRを業界現実的範囲（2-7%）に制限
            ctr = max(2.0, min(ctr, 7.0))
            
            # 信頼区間を設定（±1.0%）
            ctr_min = max(1.5, ctr - 1.0)
            ctr_max = min(8.0, ctr + 1.0)
            
            # 更新（根拠付き）
            thumbnail.predicted_ctr = round(ctr, 1)
            thumbnail.ctr_confidence = f"{ctr_min:.1f}% - {ctr_max:.1f}%"
            thumbnail.ctr_factors = ctr_factors

    def _get_hook_ctr_modifier(self, hook_score: float) -> tuple[float, str]:
        """フックスコアによるCTR補正値を計算"""
        if hook_score >= 80:
            return 1.5, "高フックスコア: +1.5%"
        elif hook_score >= 60:
            return 0.8, "中フックスコア: +0.8%"
        return 0.0, "低フックスコア: +0%"

    def _get_seo_ctr_modifiers(self, seo_metadata: Optional[SEOMetadata]) -> list[tuple[float, str]]:
        """SEOメタデータによるCTR補正値を計算"""
        modifiers = []
        if seo_metadata:
            if len(seo_metadata.title_candidates) >= 5:
                modifiers.append((0.2, "タイトル5案: +0.2%"))
            if len(seo_metadata.tags) >= 15:
                modifiers.append((0.3, "タグ15個以上: +0.3%"))
        return modifiers

    def _get_highlights_ctr_modifier(self, highlight_count: int) -> tuple[float, Optional[str]]:
        """ハイライト数によるCTR補正値を計算"""
        if highlight_count >= 5:
            return 0.5, "ハイライト5件: +0.5%"
        elif highlight_count >= 3:
            return 0.3, "ハイライト3件: +0.3%"
        return 0.0, None

    def _get_emotion_ctr_modifier(self, target_emotion: str) -> tuple[float, Optional[str]]:
        """ターゲット感情によるCTR補正値を計算"""
        emotion_bonus = {
            "好奇心": 0.8,
            "驚き": 0.6,
            "期待": 0.4
        }
        bonus = emotion_bonus.get(target_emotion, 0.0)
        if bonus > 0.0:
            return bonus, f"{target_emotion}感情: +{bonus}%"
        return 0.0, None

    async def _calculate_dynamic_ctr(
        self,
        yt_context: YouTubeOptimizedContext,
        context: Dict[str, Any]
    ) -> None:
        """Deprecated legacy alias, call _apply_dynamic_ctr_to_thumbnails instead."""
        await self._apply_dynamic_ctr_to_thumbnails(yt_context, context)
    
    async def generate_thumbnail_with_imagen(
        self,
        thumbnail: ThumbnailCandidate,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Imagen 4.0を使用してサムネイル画像を生成
        
        youtube_expert_review.md 提言:
        「Imagen 4.0によるサムネイル生成統合」
        """
        try:
            from google import genai
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
            
            # コンセプトに基づいたプロンプトを構築
            topic = context.get("topic", "")
            prompt = f"""
            YouTube thumbnail image for "{topic}".
            Concept: {thumbnail.concept}
            Target emotion: {thumbnail.target_emotion}
            Text overlay suggestion: {thumbnail.text_overlay}
            
            Style: Professional, eye-catching, high contrast.
            Requirements: 1280x720, bold colors, clear focal point.
            """
            
            result = client.models.generate_images(
                model=_resolve_model("thumbnail"),
                prompt=prompt,
                config={"number_of_images": 1}
            )
            
            if result.generated_images:
                output_dir = Path("output/thumbnails")
                output_dir.mkdir(parents=True, exist_ok=True)
                
                output_path = output_dir / f"{thumbnail.id}.png"
                result.generated_images[0].image.save(str(output_path))
                
                thumbnail.path = output_path
                return str(output_path)
                
        except Exception as e:
            logger.error(f"Imagen thumbnail generation failed: {e}")
        
        return None

    def calculate_session_continuation_score(self, current_video_id: str, series_id: str,
                                             has_end_screen: bool = True,
                                             has_teaser: bool = True,
                                             brand_consistency: float = 80.0) -> Dict[str, Any]:
        """
        [Phase 4: Session Continuation Score]
        動画公開時に「次回作へ繋がるポテンシャル」をスコア化する。
        """
        # 評価基準（モック）:
        # エンドスクリーンの有無 (+30)
        # 次回予告/CTAの有無 (+40)
        # アカウントのブランド一貫性 (+30×(score/100))
        
        score_base = 0.0
        factors = []
        
        if has_end_screen:
            score_base += 30.0
            factors.append("エンドスクリーン推奨が存在します (+30)")
        else:
            factors.append("エンドスクリーン推奨がありません (0)")
            
        if has_teaser:
            score_base += 40.0
            factors.append("明確な次回予告・CTAが存在します (+40)")
        else:
            factors.append("明確な次回予告がありません (0)")
            
        brand_score = 30.0 * (brand_consistency / 100.0)
        score_base += brand_score
        factors.append(f"ブランド一貫性の寄与 (+{brand_score:.1f})")
        
        final_score = min(100.0, score_base)
        
        logger.info(f"📈 [Session Continuation] Calculated score for {current_video_id}: {final_score:.1f}/100")
        
        return {
            "score": round(final_score, 1),
            "factors": factors,
            "series_id": series_id,
            "current_video_id": current_video_id,
            "recommendation": "次回予告の音声強化と、エンドスクリーンのクリック率改善を推奨" if final_score < 70 else "継続視聴を促す強いフックが設定されています"
        }



# シングルトンインスタンス
youtube_optimizer = YouTubeOptimizerPlugin()
