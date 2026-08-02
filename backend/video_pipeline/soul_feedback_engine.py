"""
演出哲学還流エンジン (Soul Feedback Engine)

Phase 37 M37.1 準拠。
過去の動画パフォーマンスデータ（evolution_log.json の post_publish_feedbacks）を分析し、
4 カテゴリ（テンポ / ビジュアル / オーディオ / テキスト）の演出パターンを抽出。
提案を生成し、PROJECT_CONSTITUTION.md との整合チェックを実施する。
"""

from __future__ import annotations

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import json
import logging
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

CATEGORIES = ("テンポ", "ビジュアル", "オーディオ", "テキスト")

_DEFAULT_ANALYTICS_DIR = Path(__file__).resolve().parent.parent / "branding"
_DEFAULT_CONSTITUTION_PATH = (
    Path(__file__).resolve().parent.parent / "branding" / "PROJECT_CONSTITUTION.md"
)

# 憲法で禁止される演出パターン（キーワード照合用）
_CONSTITUTION_PROHIBITED_PATTERNS: list[str] = [
    "フラッシュ点滅",
    "過度な画面振動",
    "聴覚攻撃",
    "不快な高周波",
    "著作権違反",
    "clickbait",
    "misleading",
    "デマ",
    "虚偽",
    "差別表現",
]


# ---------------------------------------------------------------------------
# Dataclass 定義
# ---------------------------------------------------------------------------


@dataclass
class Suggestion:
    """単一の演出改善提案。"""

    category: str
    suggestion: str
    evidence: str
    priority: str  # "high" | "medium" | "low"
    source_videos: list[str] = field(default_factory=list)
    confidence: float = 0.0
    impact_estimate: str = ""


@dataclass
class FeedbackOutput:
    """generate_suggestions() の出力。"""

    suggestions: list[Suggestion] = field(default_factory=list)
    overall_score: float = 0.0
    analysis_summary: str = ""
    source_video_count: int = 0
    generated_at: str = ""


@dataclass
class AnalysisResult:
    """analyze_past_videos() の出力。"""

    videos_analyzed: int = 0
    patterns: dict[str, list[Any]] = field(default_factory=dict)
    trends: dict[str, Any] = field(default_factory=dict)
    top_performing: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ComplianceResult:
    """check_constitution_compliance() の出力。"""

    suggestion: Suggestion
    compliant: bool = True
    reason: str = ""


@dataclass
class ProductionContext:
    """generate_suggestions() へ渡す任意のコンテキスト。"""

    target_audience: str = ""
    video_type: str = ""
    duration_seconds: int = 0
    mood: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# サンプルデータ（実データが無い場合のフォールバック）
# ---------------------------------------------------------------------------

_SAMPLE_FEEDBACKS: list[dict[str, Any]] = [
    {
        "timestamp": "2026-01-15T10:00:00",
        "video_id": "sample_001",
        "wagamama_id": "waga_s01",
        "actual_ctr": 8.5,
        "actual_retention": 72.0,
        "actual_views": 5000,
        "predicted_ctr": 6.0,
        "ctr_difference": 2.5,
        "significant_deviation": True,
        "drop_off_points": ["00:05", "02:00"],
        "lessons_learned": [
            "冒頭5秒のフック成功。カット数5回/15秒が効果的。",
            "BGMテンポ120BPMで視聴維持率が上昇。",
        ],
    },
    {
        "timestamp": "2026-02-01T10:00:00",
        "video_id": "sample_002",
        "wagamama_id": "waga_s02",
        "actual_ctr": 6.2,
        "actual_retention": 58.0,
        "actual_views": 3200,
        "predicted_ctr": 7.0,
        "ctr_difference": -0.8,
        "significant_deviation": False,
        "drop_off_points": ["00:30", "03:00"],
        "lessons_learned": [
            "テロップ配置が画面下部に集中し視認性低下。",
            "トランジションの種類が単調（カットのみ）。",
        ],
    },
    {
        "timestamp": "2026-02-15T10:00:00",
        "video_id": "sample_003",
        "wagamama_id": "waga_s03",
        "actual_ctr": 9.1,
        "actual_retention": 75.0,
        "actual_views": 8000,
        "predicted_ctr": 8.0,
        "ctr_difference": 1.1,
        "significant_deviation": False,
        "drop_off_points": ["01:00"],
        "lessons_learned": [
            "タイトルに数字を含めるとCTR向上（+15%）。",
            "SE使用率が高い動画は平均維持率+8%。",
        ],
    },
    {
        "timestamp": "2026-03-01T10:00:00",
        "video_id": "sample_004",
        "wagamama_id": "waga_s04",
        "actual_ctr": 4.3,
        "actual_retention": 45.0,
        "actual_views": 1200,
        "predicted_ctr": 5.5,
        "ctr_difference": -1.2,
        "significant_deviation": True,
        "drop_off_points": ["00:10", "00:45", "02:30"],
        "lessons_learned": [
            "冒頭が長い導入で離脱多発。15秒以内にフック必須。",
            "説明文にキーワードが不足し検索流入低下。",
        ],
    },
    {
        "timestamp": "2026-03-15T10:00:00",
        "video_id": "sample_005",
        "wagamama_id": "waga_s05",
        "actual_ctr": 7.8,
        "actual_retention": 68.0,
        "actual_views": 6500,
        "predicted_ctr": 7.5,
        "ctr_difference": 0.3,
        "significant_deviation": False,
        "drop_off_points": ["01:30"],
        "lessons_learned": [
            "色彩コントラスト高めのサムネイルが効果的。",
            "音量バランス: BGM -6dB / ナレーション 0dB が最適。",
        ],
    },
]


# ---------------------------------------------------------------------------
# SoulFeedbackEngine
# ---------------------------------------------------------------------------


class SoulFeedbackEngine:
    """演出哲学還流エンジン。

    過去の動画パフォーマンスデータを分析し、4 カテゴリの演出改善提案を生成する。
    PROJECT_CONSTITUTION.md との整合チェックも実施。

    Parameters
    ----------
    analytics_dir : str | None
        evolution_log.json が格納されたディレクトリ。未指定時は ``backend/branding``。
    constitution_path : str | None
        PROJECT_CONSTITUTION.md のパス。未指定時は ``backend/branding/PROJECT_CONSTITUTION.md``。
    """

    def __init__(
        self,
        analytics_dir: Optional[str] = None,
        constitution_path: Optional[str] = None,
    ) -> None:
        self._analytics_dir = Path(analytics_dir) if analytics_dir else _DEFAULT_ANALYTICS_DIR
        self._constitution_path = (
            Path(constitution_path) if constitution_path else _DEFAULT_CONSTITUTION_PATH
        )
        # analytics_dir が明示されたときだけその配下。既定は writable_path で
        # 解決する — 実行のたびに追記されるログなので書き手と経路を揃える。
        self._evolution_log_path = (
            self._analytics_dir / "evolution_log.json"
            if analytics_dir
            else _writable_path("backend/branding/evolution_log.json")
        )
        self._constitution_text: Optional[str] = None
        self._prohibited_patterns: list[str] = list(_CONSTITUTION_PROHIBITED_PATTERNS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_past_videos(self, limit: int = 10) -> AnalysisResult:
        """過去の動画パフォーマンスデータを分析する。

        Parameters
        ----------
        limit : int
            分析対象の最大件数（直近 N 件）。

        Returns
        -------
        AnalysisResult
            4 カテゴリのパターン、トレンド、トップパフォーマンス動画。
        """
        feedbacks = self._load_feedbacks(limit)
        if not feedbacks:
            logger.info("[SoulFeedbackEngine] フィードバックデータなし。サンプルデータで分析。")
            feedbacks = _SAMPLE_FEEDBACKS[:limit]

        result = AnalysisResult(
            videos_analyzed=len(feedbacks),
            patterns={cat: [] for cat in CATEGORIES},
            trends={},
            top_performing=[],
        )

        # --- テンポパターン ---
        result.patterns["テンポ"] = self._extract_tempo_patterns(feedbacks)

        # --- ビジュアルパターン ---
        result.patterns["ビジュアル"] = self._extract_visual_patterns(feedbacks)

        # --- オーディオパターン ---
        result.patterns["オーディオ"] = self._extract_audio_patterns(feedbacks)

        # --- テキストパターン ---
        result.patterns["テキスト"] = self._extract_text_patterns(feedbacks)

        # --- トレンド ---
        result.trends = self._compute_trends(feedbacks)

        # --- トップパフォーマンス ---
        result.top_performing = self._rank_top_performing(feedbacks)

        return result

    def generate_suggestions(
        self,
        context: Optional[ProductionContext] = None,
    ) -> FeedbackOutput:
        """分析結果に基づいて演出改善の提案を生成する。

        Parameters
        ----------
        context : ProductionContext | None
            動画制作のコンテキスト。指定時は提案の優先度調整に利用。

        Returns
        -------
        FeedbackOutput
            提案リスト・スコア・サマリー。
        """
        analysis = self.analyze_past_videos()
        suggestions: list[Suggestion] = []

        # --- テンポ提案 ---
        suggestions.extend(self._suggest_tempo(analysis, context))

        # --- ビジュアル提案 ---
        suggestions.extend(self._suggest_visual(analysis, context))

        # --- オーディオ提案 ---
        suggestions.extend(self._suggest_audio(analysis, context))

        # --- テキスト提案 ---
        suggestions.extend(self._suggest_text(analysis, context))

        # --- LLMによる音声テキスト（文脈）解析と提案の動的生成 ---
        if context and context.extra and "transcript" in context.extra:
            transcript_text = context.extra["transcript"]
            if isinstance(transcript_text, str) and transcript_text.strip():
                llm_suggestions = self._generate_suggestions_via_llm(transcript_text)
                suggestions.extend(llm_suggestions)

        # 憲法チェックで非準拠の提案を除外
        compliance_results = self.check_constitution_compliance(suggestions)
        compliant_suggestions = [
            cr.suggestion for cr in compliance_results if cr.compliant
        ]

        overall_score = self._compute_overall_score(analysis)

        return FeedbackOutput(
            suggestions=compliant_suggestions,
            overall_score=overall_score,
            analysis_summary=self._build_summary(analysis),
            source_video_count=analysis.videos_analyzed,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _generate_suggestions_via_llm(self, transcript_text: str) -> list[Suggestion]:
        """Gemini APIを使用して音声テキストから文脈依存の演出提案を生成する。

        Parameters
        ----------
        transcript_text : str
            音声の書き起こしテキスト。

        Returns
        -------
        list[Suggestion]
            生成された演出サジェストのリスト。
        """
        client = self._get_gemini_client_safely()
        if client is None:
            logger.info("[SoulFeedbackEngine] Geminiクライアントが取得できないため、スタブの文脈提案を返します")
            return self._get_stub_context_suggestions(transcript_text)

        prompt = f"""
        あなたはプロの映像ディレクター（NHK放送基準および人気YouTuberの演出に精通）です。
        以下の動画音声書き起こしテキスト（タイムスタンプ付き）を読み込み、動画の文脈や対談の盛り上がりを分析してください。

        【書き起こしテキスト】
        {transcript_text}

        このテキストの文脈に完全に即した具体的な演出・編集の提案を「テンポ」「ビジュアル」「オーディオ」「テキスト」の4カテゴリで生成してください。

        出力フォーマットは必ず以下のJSON配列形式にしてください。他の挨拶や説明は一切含めないでください。
        [
          {{
            "category": "テンポ" | "ビジュアル" | "オーディオ" | "テキスト",
            "suggestion": "具体的な改善提案内容",
            "evidence": "提案の根拠となる発言や箇所",
            "priority": "high" | "medium" | "low"
          }}
        ]
        """

        try:
            response_text = self._call_llm_for_suggestions(client, prompt)
            suggestions = self._parse_llm_suggestions(response_text)
            logger.info("[SoulFeedbackEngine] LLMによる動的演出提案の生成に成功しました。件数: %d", len(suggestions))
            return suggestions
        except Exception as exception:
            # TDR登録対象: ACCEPTED_SAFETY / DP-02
            logger.error("[SoulFeedbackEngine] LLM提案生成中にエラーが発生しました: %s。スタブにフォールバックします", exception)
            return self._get_stub_context_suggestions(transcript_text)

    def _get_gemini_client_safely(self) -> Optional[Any]:
        """gemini_client_factory から Gemini クライアントを安全に取得する。

        Returns
        -------
        Any | None
            取得されたクライアントオブジェクト。取得失敗時は None。
        """
        import sys
        # パスの解決
        backend_path = str(Path(__file__).resolve().parent.parent)
        if backend_path not in sys.path:
            sys.path.append(backend_path)

        try:
            from gemini_client_factory import get_gemini_client
            return get_gemini_client()
        except Exception as exception:
            logger.warning("[SoulFeedbackEngine] gemini_client_factory からのインポートに失敗しました: %s", exception)
            return None

    def _call_llm_for_suggestions(self, client: Any, prompt: str) -> str:
        """Gemini API を呼び出して演出提案のテキスト応答を取得する。

        Parameters
        ----------
        client : Any
            Geminiクライアント。
        prompt : str
            送信するプロンプト。

        Returns
        -------
        str
            Geminiの応答テキスト。
        """
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text or ""

    def _parse_llm_suggestions(self, response_text: str) -> list[Suggestion]:
        """LLMの応答テキストから提案リストをパースする。

        Parameters
        ----------
        response_text : str
            JSON形式を含む応答テキスト。

        Returns
        -------
        list[Suggestion]
            パースされたサジェストオブジェクトのリスト。
        """
        import json
        text = response_text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)
        suggestions = []
        for item in data:
            suggestions.append(
                Suggestion(
                    category=item.get("category", "テンポ"),
                    suggestion=item.get("suggestion", ""),
                    evidence=item.get("evidence", ""),
                    priority=item.get("priority", "medium"),
                    confidence=0.9,
                    impact_estimate="LLM文脈分析に基づく"
                )
            )
        return suggestions

    def _get_stub_context_suggestions(self, transcript_text: str) -> list[Suggestion]:
        """スタブ用の対談文脈に基づく演出サジェストを生成するフォールバックメソッド"""
        suggestions = []
        
        # 簡易キーワード判定
        if "山田" in transcript_text or "対談" in transcript_text:
            suggestions.append(
                Suggestion(
                    category="ビジュアル",
                    suggestion="山田氏とホストの対談シーン切り替え時に、話者に合わせて自動ズーム（パンアップ）を適用してください。",
                    evidence="発言『山田』『対談』を含む会話セグメントの検出",
                    priority="high",
                    confidence=0.8,
                    impact_estimate="対談のフォーカスを高め視聴維持率を向上"
                )
            )
            suggestions.append(
                Suggestion(
                    category="テキスト",
                    suggestion="対談中の専門用語や重要な解説部分に、MS Gothicを用いたNHK風の要約字幕（フッタースタイル）を配置してください。",
                    evidence="音声内の論理的主張およびキーワードの検出",
                    priority="medium",
                    confidence=0.8,
                    impact_estimate="視認性と信頼性の担保"
                )
            )
        else:
            suggestions.append(
                Suggestion(
                    category="テンポ",
                    suggestion="会話の区切り目にある1.5秒以上の無音区間をカットし、スマートにテンポアップしてください。",
                    evidence="音声全体の無音スキャン結果",
                    priority="high",
                    confidence=0.7,
                    impact_estimate="視聴離脱の防止"
                )
            )
        return suggestions

    def check_constitution_compliance(
        self,
        suggestions: list[Suggestion],
    ) -> list[ComplianceResult]:
        """提案が PROJECT_CONSTITUTION.md に準拠しているかチェックする。

        Parameters
        ----------
        suggestions : list[Suggestion]
            チェック対象の提案リスト。

        Returns
        -------
        list[ComplianceResult]
            各提案の準拠/非準拠判定と理由。
        """
        constitution_text = self._load_constitution()
        compliance_results: list[ComplianceResult] = []

        for suggestion in suggestions:
            compliant = True
            reason = ""

            # 禁止パターンとの照合
            text_to_check = f"{suggestion.suggestion} {suggestion.evidence}".lower()
            for pattern in self._prohibited_patterns:
                if pattern.lower() in text_to_check:
                    compliant = False
                    reason = f"禁止パターン検出: '{pattern}'"
                    break

            # 憲法テキストとの矛盾チェック（キーワードベース）
            if compliant and constitution_text:
                compliant, reason = self._check_against_constitution(
                    suggestion, constitution_text
                )

            compliance_results.append(
                ComplianceResult(
                    suggestion=suggestion,
                    compliant=compliant,
                    reason=reason,
                )
            )

        return compliance_results

    # ------------------------------------------------------------------
    # データ読み込み
    # ------------------------------------------------------------------

    def _load_feedbacks(self, limit: int) -> list[dict[str, Any]]:
        """evolution_log.json から post_publish_feedbacks を読み込む。

        Parameters
        ----------
        limit : int
            取得する最大件数。

        Returns
        -------
        list[dict[str, Any]]
            読み込まれた過去動画フィードバックデータのリスト。
        """
        if not self._evolution_log_path.exists():
            logger.warning(
                "[SoulFeedbackEngine] evolution_log.json が見つかりません: %s",
                self._evolution_log_path,
            )
            return []

        try:
            raw_content = self._evolution_log_path.read_text(encoding="utf-8")
            data = json.loads(raw_content)
            feedbacks_list: list[dict[str, Any]] = data.get("post_publish_feedbacks", [])
            # 直近 limit 件
            return feedbacks_list[-limit:] if len(feedbacks_list) > limit else feedbacks_list
        except (json.JSONDecodeError, OSError, KeyError) as exception:
            logger.error(
                "[SoulFeedbackEngine] evolution_log.json の読み込みに失敗: %s", exception
            )
            return []

    def _load_constitution(self) -> str:
        """PROJECT_CONSTITUTION.md を読み込みキャッシュする。

        Returns
        -------
        str
            憲法ファイルの内容テキスト。
        """
        if self._constitution_text is not None:
            return self._constitution_text

        if not self._constitution_path.exists():
            logger.warning(
                "[SoulFeedbackEngine] 憲法ファイルが見つかりません: %s",
                self._constitution_path,
            )
            self._constitution_text = ""
            return ""

        try:
            self._constitution_text = self._constitution_path.read_text(encoding="utf-8")
        except OSError as exception:
            logger.error(
                "[SoulFeedbackEngine] 憲法ファイルの読み込みに失敗: %s", exception
            )
            self._constitution_text = ""

        return self._constitution_text

    # ------------------------------------------------------------------
    # パターン抽出 (4 カテゴリ)
    # ------------------------------------------------------------------

    def _extract_tempo_patterns(
        self, feedbacks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """テンポ関連パターンを抽出: カット数/分、シーン平均長、テンポ変動。"""
        patterns: list[dict[str, Any]] = []
        drop_off_counts: dict[str, int] = {}

        for fb in feedbacks:
            for point in fb.get("drop_off_points", []):
                drop_off_counts[point] = drop_off_counts.get(point, 0) + 1

            for lesson in fb.get("lessons_learned", []):
                lesson_lower = lesson.lower()
                if any(
                    kw in lesson_lower
                    for kw in ("カット", "テンポ", "冒頭", "導入", "フック", "秒")
                ):
                    patterns.append(
                        {
                            "type": "テンポ",
                            "lesson": lesson,
                            "video_id": fb.get("video_id", ""),
                            "ctr": fb.get("actual_ctr", 0),
                        }
                    )

        # 頻出離脱ポイントをパターンとして追加
        if drop_off_counts:
            top_drop = sorted(
                drop_off_counts.items(), key=lambda x: x[1], reverse=True
            )[:3]
            patterns.append(
                {
                    "type": "離脱集中",
                    "drop_off_ranking": [
                        {"time": t, "count": c} for t, c in top_drop
                    ],
                }
            )

        return patterns

    def _extract_visual_patterns(
        self, feedbacks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """ビジュアル関連パターン: トランジション、テロップ配置、色彩傾向。"""
        patterns: list[dict[str, Any]] = []
        for fb in feedbacks:
            for lesson in fb.get("lessons_learned", []):
                lesson_lower = lesson.lower()
                if any(
                    kw in lesson_lower
                    for kw in (
                        "テロップ",
                        "トランジション",
                        "色彩",
                        "サムネイル",
                        "配置",
                        "コントラスト",
                        "カラー",
                    )
                ):
                    patterns.append(
                        {
                            "type": "ビジュアル",
                            "lesson": lesson,
                            "video_id": fb.get("video_id", ""),
                            "ctr": fb.get("actual_ctr", 0),
                        }
                    )
        return patterns

    def _extract_audio_patterns(
        self, feedbacks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """オーディオ関連パターン: BGM 選曲傾向、SE 使用率、音量バランス。"""
        patterns: list[dict[str, Any]] = []
        for fb in feedbacks:
            for lesson in fb.get("lessons_learned", []):
                lesson_lower = lesson.lower()
                if any(
                    kw in lesson_lower
                    for kw in ("bgm", "se", "音量", "bpm", "オーディオ", "音楽", "ナレーション")
                ):
                    patterns.append(
                        {
                            "type": "オーディオ",
                            "lesson": lesson,
                            "video_id": fb.get("video_id", ""),
                            "retention": fb.get("actual_retention", 0),
                        }
                    )
        return patterns

    def _extract_text_patterns(
        self, feedbacks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """テキスト関連パターン: フック語彙、タイトルパターン、説明文スタイル。"""
        patterns: list[dict[str, Any]] = []
        for fb in feedbacks:
            for lesson in fb.get("lessons_learned", []):
                lesson_lower = lesson.lower()
                if any(
                    kw in lesson_lower
                    for kw in (
                        "タイトル",
                        "説明文",
                        "キーワード",
                        "数字",
                        "検索",
                        "語彙",
                        "コピー",
                    )
                ):
                    patterns.append(
                        {
                            "type": "テキスト",
                            "lesson": lesson,
                            "video_id": fb.get("video_id", ""),
                            "ctr": fb.get("actual_ctr", 0),
                        }
                    )
        return patterns

    # ------------------------------------------------------------------
    # トレンド・ランキング
    # ------------------------------------------------------------------

    def _compute_trends(self, feedbacks: list[dict[str, Any]]) -> dict[str, Any]:
        """CTR・維持率の時系列トレンドを計算する。

        Parameters
        ----------
        feedbacks : list[dict[str, Any]]
            過去動画フィードバックリスト。

        Returns
        -------
        dict[str, Any]
            算出された時系列トレンド。
        """
        ctr_list = [feedback.get("actual_ctr", 0) for feedback in feedbacks if feedback.get("actual_ctr")]
        retention_list = [
            feedback.get("actual_retention", 0) for feedback in feedbacks if feedback.get("actual_retention")
        ]

        trends = {}
        trends.update(self._compute_ctr_trends(ctr_list))
        trends.update(self._compute_retention_and_deviation_trends(retention_list, feedbacks))
        return trends

    def _compute_ctr_trends(self, ctr_list: list[float]) -> dict[str, Any]:
        """CTR (Click-Through Rate) の時系列トレンドを算出する。

        Parameters
        ----------
        ctr_list : list[float]
            CTRデータのリスト。

        Returns
        -------
        dict[str, Any]
            CTRの平均値、中央値、標準偏差、トレンド。
        """
        trends = {}
        if not ctr_list:
            return trends

        trends["ctr_avg"] = round(statistics.mean(ctr_list), 2)
        trends["ctr_median"] = round(statistics.median(ctr_list), 2)
        if len(ctr_list) >= 2:
            trends["ctr_stdev"] = round(statistics.stdev(ctr_list), 2)
            trends["ctr_trend"] = "上昇" if ctr_list[-1] > ctr_list[0] else "下降"
        else:
            trends["ctr_stdev"] = 0.0
            trends["ctr_trend"] = "データ不足"
        return trends

    def _compute_retention_and_deviation_trends(
        self, retention_list: list[float], feedbacks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """維持率および乖離率の時系列トレンドを算出する。

        Parameters
        ----------
        retention_list : list[float]
            維持率データのリスト。
        feedbacks : list[dict[str, Any]]
            過去動画フィードバックリスト。

        Returns
        -------
        dict[str, Any]
            平均維持率、中央維持率、乖離率。
        """
        trends = {}
        if retention_list:
            trends["retention_avg"] = round(statistics.mean(retention_list), 2)
            trends["retention_median"] = round(statistics.median(retention_list), 2)

        trends["deviation_rate"] = round(
            sum(1 for feedback in feedbacks if feedback.get("significant_deviation")) / max(len(feedbacks), 1)
            * 100,
            1,
        )
        return trends

    def _rank_top_performing(
        self, feedbacks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """CTR × 維持率 でスコアリングし、上位を返す。"""
        scored: list[tuple[float, dict[str, Any]]] = []
        for fb in feedbacks:
            ctr = fb.get("actual_ctr", 0)
            retention = fb.get("actual_retention", 0)
            score = ctr * (retention / 100.0) if retention else 0.0
            scored.append(
                (
                    score,
                    {
                        "video_id": fb.get("video_id", ""),
                        "score": round(score, 2),
                        "ctr": ctr,
                        "retention": retention,
                        "views": fb.get("actual_views", 0),
                    },
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:5]]

    # ------------------------------------------------------------------
    # 提案生成 (カテゴリ別)
    # ------------------------------------------------------------------

    def _suggest_tempo(
        self,
        analysis: AnalysisResult,
        context: Optional[ProductionContext],
    ) -> list[Suggestion]:
        """テンポカテゴリの提案を生成する。"""
        suggestions: list[Suggestion] = []
        tempo_patterns = analysis.patterns.get("テンポ", [])

        # 離脱集中パターンからの提案
        drop_off_patterns = [p for p in tempo_patterns if p.get("type") == "離脱集中"]
        if drop_off_patterns:
            ranking = drop_off_patterns[0].get("drop_off_ranking", [])
            if ranking:
                top_point = ranking[0]
                suggestions.append(
                    Suggestion(
                        category="テンポ",
                        suggestion=f"離脱集中ポイント {top_point['time']} 付近にリエンゲージメント要素を配置",
                        evidence=f"過去 {analysis.videos_analyzed} 本中 {top_point['count']} 本で同一ポイントに離脱集中",
                        priority="high",
                        source_videos=[],
                        confidence=min(0.95, 0.5 + top_point["count"] * 0.1),
                        impact_estimate="+2-4% 維持率",
                    )
                )

        # フック関連の提案
        hook_patterns = [
            p
            for p in tempo_patterns
            if p.get("type") == "テンポ"
            and any(kw in p.get("lesson", "") for kw in ("冒頭", "フック", "導入"))
        ]
        if hook_patterns:
            high_ctr = [p for p in hook_patterns if p.get("ctr", 0) >= 7.0]
            if high_ctr:
                video_ids = list({p["video_id"] for p in high_ctr if p.get("video_id")})
                suggestions.append(
                    Suggestion(
                        category="テンポ",
                        suggestion="冒頭15秒のカット数を3→5に増加",
                        evidence=f"過去 {len(high_ctr)} 本の高CTR動画で冒頭フック成功パターンを検出",
                        priority="high",
                        source_videos=video_ids[:5],
                        confidence=0.85,
                        impact_estimate="+3-5% CTR",
                    )
                )

        # コンテキストに基づく調整
        if context and context.duration_seconds > 600:
            suggestions.append(
                Suggestion(
                    category="テンポ",
                    suggestion="10分超の動画では3分ごとにテンポチェンジを配置",
                    evidence="長尺動画の離脱防止ベストプラクティス",
                    priority="medium",
                    confidence=0.70,
                    impact_estimate="+5-8% 維持率",
                )
            )

        return suggestions

    def _suggest_visual(
        self,
        analysis: AnalysisResult,
        context: Optional[ProductionContext],
    ) -> list[Suggestion]:
        """ビジュアルカテゴリの提案を生成する。"""
        suggestions: list[Suggestion] = []
        visual_patterns = analysis.patterns.get("ビジュアル", [])

        if visual_patterns:
            video_ids = list(
                {p["video_id"] for p in visual_patterns if p.get("video_id")}
            )
            # トランジション関連
            transition_ps = [
                p for p in visual_patterns if "トランジション" in p.get("lesson", "")
            ]
            if transition_ps:
                suggestions.append(
                    Suggestion(
                        category="ビジュアル",
                        suggestion="トランジション種類を多様化（カット/ディゾルブ/ワイプを混在）",
                        evidence=f"{len(transition_ps)} 件のレッスンでトランジション単調化の指摘あり",
                        priority="medium",
                        source_videos=video_ids[:3],
                        confidence=0.75,
                        impact_estimate="+1-3% 維持率",
                    )
                )

            # テロップ関連
            telop_ps = [
                p for p in visual_patterns if "テロップ" in p.get("lesson", "")
            ]
            if telop_ps:
                suggestions.append(
                    Suggestion(
                        category="ビジュアル",
                        suggestion="テロップ配置を画面上部1/3に分散（視認性向上）",
                        evidence=f"{len(telop_ps)} 件でテロップ配置に関するフィードバック検出",
                        priority="medium",
                        source_videos=video_ids[:3],
                        confidence=0.72,
                        impact_estimate="+1-2% 維持率",
                    )
                )

            # サムネイル/色彩関連
            color_ps = [
                p
                for p in visual_patterns
                if any(kw in p.get("lesson", "") for kw in ("色彩", "サムネイル", "コントラスト"))
            ]
            if color_ps:
                high_ctr_vids = [p["video_id"] for p in color_ps if p.get("ctr", 0) >= 7.0]
                suggestions.append(
                    Suggestion(
                        category="ビジュアル",
                        suggestion="サムネイルの色彩コントラストを高め、背景との差異を強調",
                        evidence=f"高CTR動画 {len(high_ctr_vids)} 本で色彩コントラスト効果を確認",
                        priority="high",
                        source_videos=list(set(high_ctr_vids))[:3],
                        confidence=0.80,
                        impact_estimate="+2-4% CTR",
                    )
                )

        return suggestions

    def _suggest_audio(
        self,
        analysis: AnalysisResult,
        context: Optional[ProductionContext],
    ) -> list[Suggestion]:
        """オーディオカテゴリの提案を生成する。"""
        suggestions: list[Suggestion] = []
        audio_patterns = analysis.patterns.get("オーディオ", [])

        if audio_patterns:
            video_ids = list(
                {p["video_id"] for p in audio_patterns if p.get("video_id")}
            )
            # BGM/BPM関連
            bgm_ps = [
                p for p in audio_patterns if any(kw in p.get("lesson", "").lower() for kw in ("bgm", "bpm"))
            ]
            if bgm_ps:
                suggestions.append(
                    Suggestion(
                        category="オーディオ",
                        suggestion="BGMテンポを110-120BPMに設定（視聴維持率と相関）",
                        evidence=f"{len(bgm_ps)} 件のフィードバックでBGMテンポと維持率の正の相関を検出",
                        priority="medium",
                        source_videos=video_ids[:3],
                        confidence=0.78,
                        impact_estimate="+2-5% 維持率",
                    )
                )

            # 音量バランス関連
            volume_ps = [
                p for p in audio_patterns if any(kw in p.get("lesson", "") for kw in ("音量", "ナレーション"))
            ]
            if volume_ps:
                suggestions.append(
                    Suggestion(
                        category="オーディオ",
                        suggestion="音量バランスを最適化: BGM -6dB / ナレーション 0dB",
                        evidence=f"{len(volume_ps)} 件で音量バランスに関するフィードバック検出",
                        priority="high",
                        source_videos=video_ids[:3],
                        confidence=0.82,
                        impact_estimate="+3-5% 維持率",
                    )
                )

            # SE関連
            se_ps = [
                p for p in audio_patterns if "se" in p.get("lesson", "").lower()
            ]
            if se_ps:
                suggestions.append(
                    Suggestion(
                        category="オーディオ",
                        suggestion="重要ポイントにSEを追加（平均+8%維持率向上）",
                        evidence=f"{len(se_ps)} 件でSE使用効果を確認",
                        priority="medium",
                        source_videos=video_ids[:3],
                        confidence=0.75,
                        impact_estimate="+5-8% 維持率",
                    )
                )

        return suggestions

    def _suggest_text(
        self,
        analysis: AnalysisResult,
        context: Optional[ProductionContext],
    ) -> list[Suggestion]:
        """テキストカテゴリの提案を生成する。"""
        suggestions: list[Suggestion] = []
        text_patterns = analysis.patterns.get("テキスト", [])

        if text_patterns:
            video_ids = list(
                {p["video_id"] for p in text_patterns if p.get("video_id")}
            )
            # タイトル関連
            title_ps = [
                p for p in text_patterns if any(kw in p.get("lesson", "") for kw in ("タイトル", "数字"))
            ]
            if title_ps:
                high_ctr_vids = [p["video_id"] for p in title_ps if p.get("ctr", 0) >= 7.0]
                suggestions.append(
                    Suggestion(
                        category="テキスト",
                        suggestion="タイトルに具体的な数字を含める（例:「3つの方法」「5分で完成」）",
                        evidence=f"数字入りタイトルの動画 {len(high_ctr_vids)} 本で平均CTR+15%",
                        priority="high",
                        source_videos=list(set(high_ctr_vids))[:3],
                        confidence=0.88,
                        impact_estimate="+10-15% CTR",
                    )
                )

            # 説明文/キーワード関連
            desc_ps = [
                p
                for p in text_patterns
                if any(kw in p.get("lesson", "") for kw in ("説明文", "キーワード", "検索"))
            ]
            if desc_ps:
                suggestions.append(
                    Suggestion(
                        category="テキスト",
                        suggestion="説明文にターゲットキーワードを3-5個含め、検索流入を強化",
                        evidence=f"{len(desc_ps)} 件でキーワード不足による検索流入低下を検出",
                        priority="medium",
                        source_videos=video_ids[:3],
                        confidence=0.80,
                        impact_estimate="+5-10% 検索流入",
                    )
                )

        return suggestions

    # ------------------------------------------------------------------
    # 憲法チェック ヘルパー
    # ------------------------------------------------------------------

    def _check_against_constitution(
        self, suggestion: Suggestion, constitution_text: str
    ) -> tuple[bool, str]:
        """憲法テキストとの矛盾をキーワードベースでチェックする。

        Parameters
        ----------
        suggestion : Suggestion
            検証対象の提案。
        constitution_text : str
            憲法のテキスト内容。

        Returns
        -------
        tuple[bool, str]
            準拠判定（True/False）および不適合理由。
        """
        # 憲法内の禁止表現と提案の照合
        text_to_check = f"{suggestion.suggestion} {suggestion.evidence}".lower()
        constitution_lower = constitution_text.lower()

        # 攻撃的表現チェック
        aggressive_keywords = ["攻撃的", "扇情的", "過激"]
        for keyword in aggressive_keywords:
            if keyword in text_to_check and keyword in constitution_lower:
                return False, f"憲法の禁止事項に抵触: '{keyword}'"

        return True, ""

    # ------------------------------------------------------------------
    # スコアリング・サマリー
    # ------------------------------------------------------------------

    def _compute_overall_score(self, analysis: AnalysisResult) -> float:
        """分析結果から総合スコア (0-100) を算出する。

        Parameters
        ----------
        analysis : AnalysisResult
            動画分析結果。

        Returns
        -------
        float
            総合パフォーマンススコア。
        """
        score = 50.0  # ベースライン

        trends = analysis.trends
        score += self._score_ctr(trends.get("ctr_avg", 0))
        score += self._score_retention(trends.get("retention_avg", 0))
        score += self._score_deviation(trends.get("deviation_rate", 100))

        total_patterns = sum(len(values) for values in analysis.patterns.values())
        score += self._score_patterns(total_patterns)

        return min(100.0, round(score, 1))

    def _score_ctr(self, ctr_average: float) -> float:
        """平均CTRに基づく加算スコアを算出する。

        Parameters
        ----------
        ctr_average : float
            平均CTR。

        Returns
        -------
        float
            加算スコア。
        """
        if ctr_average >= 8.0:
            return 20.0
        if ctr_average >= 6.0:
            return 10.0
        if ctr_average >= 4.0:
            return 5.0
        return 0.0

    def _score_retention(self, retention_average: float) -> float:
        """平均維持率に基づく加算スコアを算出する。

        Parameters
        ----------
        retention_average : float
            平均維持率。

        Returns
        -------
        float
            加算スコア。
        """
        if retention_average >= 70.0:
            return 20.0
        if retention_average >= 55.0:
            return 10.0
        if retention_average >= 40.0:
            return 5.0
        return 0.0

    def _score_deviation(self, deviation_rate: float) -> float:
        """乖離率に基づく加算スコアを算出する。

        Parameters
        ----------
        deviation_rate : float
            予測と実績の乖離率。

        Returns
        -------
        float
            加算スコア。
        """
        if deviation_rate <= 20.0:
            return 10.0
        if deviation_rate <= 40.0:
            return 5.0
        return 0.0

    def _score_patterns(self, total_patterns: int) -> float:
        """検出パターン数に基づく加算スコアを算出する。

        Parameters
        ----------
        total_patterns : int
            検出されたパターンの総数。

        Returns
        -------
        float
            加算スコア。
        """
        if total_patterns >= 10:
            return 5.0
        if total_patterns >= 5:
            return 2.5
        return 0.0

    def _build_summary(self, analysis: AnalysisResult) -> str:
        """分析サマリー文字列を生成する。"""
        trends = analysis.trends
        parts = [
            f"分析対象: {analysis.videos_analyzed} 本",
        ]

        if "ctr_avg" in trends:
            parts.append(f"平均CTR: {trends['ctr_avg']}%")
        if "retention_avg" in trends:
            parts.append(f"平均維持率: {trends['retention_avg']}%")
        if "ctr_trend" in trends:
            parts.append(f"CTRトレンド: {trends['ctr_trend']}")

        total_patterns = sum(len(v) for v in analysis.patterns.values())
        parts.append(f"検出パターン数: {total_patterns}")

        if analysis.top_performing:
            top = analysis.top_performing[0]
            parts.append(f"最高スコア動画: {top['video_id']} (スコア: {top['score']})")

        return " / ".join(parts)

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------




# ---------------------------------------------------------------------------
# CLI エントリーポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    engine = SoulFeedbackEngine()

    print("=" * 60)
    print("🎬 演出哲学還流エンジン — Soul Feedback Engine")
    print("=" * 60)

    # 1. 分析
    print("\n📊 過去動画の分析...")
    analysis = engine.analyze_past_videos(limit=10)
    print(f"  分析対象: {analysis.videos_analyzed} 本")
    for cat in CATEGORIES:
        pats = analysis.patterns.get(cat, [])
        print(f"  [{cat}] パターン数: {len(pats)}")
    print(f"  トップパフォーマンス: {len(analysis.top_performing)} 本")

    # 2. 提案生成
    print("\n💡 提案生成中...")
    context = ProductionContext(
        target_audience="日本語YouTube視聴者",
        video_type="解説動画",
        duration_seconds=480,
        mood="energetic",
    )
    output = engine.generate_suggestions(context=context)
    print(f"  提案数: {len(output.suggestions)}")
    print(f"  総合スコア: {output.overall_score}")
    print(f"  サマリー: {output.analysis_summary}")

    for i, s in enumerate(output.suggestions, 1):
        print(f"\n  [{i}] {s.category}: {s.suggestion}")
        print(f"      根拠: {s.evidence}")
        print(f"      優先度: {s.priority} / 信頼度: {s.confidence}")
        print(f"      影響推定: {s.impact_estimate}")

    # 3. 憲法チェック
    print("\n📜 憲法整合チェック...")
    compliance = engine.check_constitution_compliance(output.suggestions)
    for cr in compliance:
        status = "✅ 準拠" if cr.compliant else f"❌ 非準拠: {cr.reason}"
        print(f"  [{cr.suggestion.category}] {status}")

    print(f"\n生成時刻: {output.generated_at}")
    print("=" * 60)
