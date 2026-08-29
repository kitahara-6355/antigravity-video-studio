"""
Progressive Review Plugin - 段階的レビュー機能

PROJECT_CONSTITUTION §16 拡張:
- 各Phase完了時にレポート生成
- 統一感・雰囲気の確認
- 修正指示→再生成ループ
- ユーザー成長支援
"""
from core import Plugin, PluginPhase, ProductionContext
from typing import Dict, Any, List, Optional, Literal
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class ReviewStage(Enum):
    """レビューステージ"""
    SUBTITLE = "subtitle"           # Stage 1: 字幕統一感
    TELOP = "telop"                 # Stage 2: テロップデザイン
    VISUAL = "visual"               # Stage 3: サムネイル・画像
    VIDEO = "video"                 # Stage 4: OP/ED・トランジション
    FINAL = "final"                 # Stage 5: 最終統合


@dataclass
class ReviewItem:
    """レビュー項目"""
    id: str
    type: str
    preview_path: Optional[str] = None
    preview_data: Optional[str] = None  # base64 or URL
    content: Optional[str] = None
    issues: List[str] = field(default_factory=list)
    passed: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


def _測ったスコア(reviews: Dict[Any, Any]) -> List[float]:
    """**中身を採点したステージのスコアだけ**（R1.5-C4）。

    除くのは2種類:

    - `overall_score is None` — 見るものはあったが1つも測れなかった
    - `items` が空 — **そもそも見るものが無い**（点は 100.0 だが中身は無い）

    後者を混ぜていたため、**1項目も採点していないのに
    `summary.overall_score = 100.0` を名乗っていた**（基準 `8eef716` は 80.0。
    gate-verifier 4周目の指摘 C-5）。ステージごとの 100.0 は元からの挙動なので
    残すが、**それを集計して「全体の点」として出すのは別の主張**になる。
    """
    return [r.overall_score for r in reviews.values()
            if r.items and r.overall_score is not None]


@dataclass
class StageReview:
    """ステージレビュー結果"""
    stage: ReviewStage
    items: List[ReviewItem]
    # **None は「1つも測っていない」。** 0.0（＝全部落ちた）と区別する（R1.5-C4）
    overall_score: Optional[float]
    consistency_score: float
    issues: List[str]
    suggestions: List[str]
    approved: bool = False
    revision_requested: bool = False
    revision_notes: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class ProgressiveReviewPlugin(Plugin):
    """
    段階的レビュープラグイン
    
    5段階のレビューポイントで制作物を確認し、
    各段階で修正指示を可能にする。
    """
    
    name = "progressive_review"
    phase = PluginPhase.POST_PROCESS
    priority = 50
    
    STAGES = [
        ReviewStage.SUBTITLE,
        ReviewStage.TELOP,
        ReviewStage.VISUAL,
        ReviewStage.VIDEO,
        ReviewStage.FINAL
    ]
    
    STAGE_NAMES = {
        ReviewStage.SUBTITLE: "字幕統一感チェック",
        ReviewStage.TELOP: "テロップデザインチェック",
        ReviewStage.VISUAL: "サムネイル・画像チェック",
        ReviewStage.VIDEO: "OP/ED・トランジションチェック",
        ReviewStage.FINAL: "最終統合チェック"
    }
    
    def __init__(self):
        super().__init__()
        self._reviews: Dict[ReviewStage, StageReview] = {}
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """Progressive Reviewを実行"""
        self.log("Starting Progressive Review")
        
        # 全ステージのレビューを生成
        for stage in self.STAGES:
            review = self._generate_stage_review(stage, context)
            self._reviews[stage] = review
            context.set_extension(f"review_{stage.value}", review.__dict__)
        
        # サマリーを生成
        summary = self._generate_summary(context)
        context.set_extension("progressive_review_summary", summary)
        
        self.log(f"Progressive Review completed: {len(self._reviews)} stages")
        return context
    
    def generate_stage_report(
        self,
        stage: ReviewStage,
        context: ProductionContext
    ) -> str:
        """特定ステージのMarkdownレポートを生成"""
        review = self._generate_stage_review(stage, context)
        return self._format_stage_report(review)
    
    def _generate_stage_review(
        self,
        stage: ReviewStage,
        context: ProductionContext
    ) -> StageReview:
        """ステージレビューを生成"""
        items = []
        issues = []
        suggestions = []
        
        if stage == ReviewStage.SUBTITLE:
            items, issues, suggestions = self._review_subtitles(context)
        elif stage == ReviewStage.TELOP:
            items, issues, suggestions = self._review_telops(context)
        elif stage == ReviewStage.VISUAL:
            items, issues, suggestions = self._review_visuals(context)
        elif stage == ReviewStage.VIDEO:
            items, issues, suggestions = self._review_videos(context)
        elif stage == ReviewStage.FINAL:
            items, issues, suggestions = self._review_final(context)
        
        # スコア計算
        # **測っていない項目は合否の分母に入れない**（R1.5-C4）。
        # 合格に数えれば偽の success、不合格に数えれば偽の測定結果になる。
        #
        # **1つも測っていないときは 100.0 ではなく None。** 分母が空のときに
        # 100.0 を返していたら、何ひとつ測っていない状態で
        # 「全体スコア 100.0/100・レンダリング準備完了」と名乗るようになった
        # （gate-verifier 2周目の指摘）。0.0 を返す以前より強い偽の success で、
        # 直し方が間違っていた。**測っていないなら点をつけない。**
        # **見るものが無いステージ**（items が空）と、**見るものはあったが
        # 1つも測れなかったステージ**は別。前者は元からの 100.0 のままにし、
        # 後者だけ None にする。条件文が名指ししているのは後者。
        測った = [i for i in items if i.metadata.get("measured") is not False]
        passed_count = sum(1 for item in 測った if item.passed)
        if 測った:
            overall_score = passed_count / len(測った) * 100
        elif items:
            overall_score = None      # 測れなかった。点をつけない
        else:
            overall_score = 100.0     # 見るものが無い（従来どおり）
        consistency_score = self._calculate_consistency(items, stage)
        
        return StageReview(
            stage=stage,
            items=items,
            overall_score=overall_score,
            consistency_score=consistency_score,
            issues=issues,
            suggestions=suggestions
        )
    
    def _review_single_subtitle(self, idx: int, segment: Dict[str, Any]) -> ReviewItem:
        """単一の字幕セグメントをレビューしてReviewItemを生成"""
        text = segment.get("text", "")
        start = segment.get("start", 0)
        end = segment.get("end", 0)
        
        # 例外フォールバックのための安全な数値変換
        try:
            start_val = float(start) if start is not None else 0.0
            end_val = float(end) if end is not None else 0.0
            duration = end_val - start_val
        except (TypeError, ValueError):
            start_val = 0.0
            end_val = 0.0
            duration = 0.0
        
        item_issues = []
        
        # 長さチェック
        if duration < 0.5:
            item_issues.append("表示時間が短すぎます（0.5秒未満）")
        elif duration > 6.0:
            item_issues.append("表示時間が長すぎます（6秒超）")
        
        # 文字数チェック
        if len(text) > 40:
            item_issues.append("文字数が多すぎます（40文字超）")
        
        return ReviewItem(
            id=f"subtitle_{idx}",
            type="subtitle",
            content=text,
            issues=item_issues,
            passed=len(item_issues) == 0,
            metadata={"start": start_val, "end": end_val, "duration": duration}
        )

    def _review_subtitles(self, context: ProductionContext) -> tuple:
        """字幕レビュー"""
        items = []
        issues = []
        suggestions = []
        
        segments = context.get_extension("segments", [])
        durations = []
        
        for i, seg in enumerate(segments):
            item = self._review_single_subtitle(i, seg)
            items.append(item)
            duration = item.metadata.get("duration", 0.0)
            durations.append(duration)
        
        # 全体の統一感チェック
        if durations:
            avg_duration = sum(durations) / len(durations)
            variance = sum((d - avg_duration) ** 2 for d in durations) / len(durations)
            if variance > 4.0:
                issues.append("字幕の表示時間にばらつきがあります")
                suggestions.append("平均表示時間に近づけるとリズムが整います")
        
        return items, issues, suggestions
    
    def _review_telops(self, context: ProductionContext) -> tuple:
        """テロップレビュー"""
        items = []
        issues = []
        suggestions = []
        
        telops = context.get_extension("telop_candidates", [])
        design_tokens = context.mood_settings or {}
        
        expected_colors = design_tokens.get("color_palette", {})
        
        for i, telop in enumerate(telops):
            item_issues = []
            
            # デザイントークンとの整合性チェック
            telop_color = telop.get("color")
            if expected_colors and telop_color:
                if telop_color not in expected_colors.values():
                    item_issues.append("カラーパレットと不一致")
            
            items.append(ReviewItem(
                id=f"telop_{i}",
                type="telop",
                content=telop.get("text", ""),
                preview_data=telop.get("preview"),
                issues=item_issues,
                passed=len(item_issues) == 0,
                metadata=telop
            ))
        
        if not telops:
            suggestions.append("テロップが設定されていません")
        
        return items, issues, suggestions
    
    def _review_visuals(self, context: ProductionContext) -> tuple:
        """ビジュアル素材レビュー"""
        items = []
        issues = []
        suggestions = []
        
        # サムネイル
        thumbnails = context.thumbnail_candidates or []
        for i, thumb in enumerate(thumbnails):
            items.append(ReviewItem(
                id=f"thumbnail_{i}",
                type="thumbnail",
                preview_path=thumb if isinstance(thumb, str) else None,
                preview_data=thumb if not isinstance(thumb, str) else None,
                passed=True,
                metadata={"index": i}
            ))
        
        # シーン画像
        scenes = context.get_extension("scenes", [])
        for i, scene in enumerate(scenes):
            image = scene.get("image")
            if image:
                items.append(ReviewItem(
                    id=f"scene_{i}",
                    type="scene_image",
                    preview_data=image,
                    content=scene.get("name", f"Scene {i+1}"),
                    passed=True,
                    metadata=scene
                ))
        
        # トーン統一チェック
        if len(thumbnails) > 1:
            suggestions.append("複数のサムネイル候補があります。トーンの統一感を確認してください")
        
        return items, issues, suggestions
    
    def _review_videos(self, context: ProductionContext) -> tuple:
        """動画素材レビュー"""
        items = []
        issues = []
        suggestions = []
        
        # オープニング
        if context.opening:
            items.append(ReviewItem(
                id="opening",
                type="opening_video",
                preview_path=context.opening,
                content="オープニング動画",
                passed=True
            ))
        else:
            issues.append("オープニング動画が設定されていません")
        
        # エンディング
        if context.ending:
            items.append(ReviewItem(
                id="ending",
                type="ending_video",
                preview_path=context.ending,
                content="エンディング動画",
                passed=True
            ))
        else:
            issues.append("エンディング動画が設定されていません")
        
        # トランジション
        transitions = context.get_extension("transitions", [])
        for i, trans in enumerate(transitions):
            items.append(ReviewItem(
                id=f"transition_{i}",
                type="transition",
                content=trans.get("type", "unknown"),
                passed=True,
                metadata=trans
            ))
        
        return items, issues, suggestions
    
    def _review_final(self, context: ProductionContext) -> tuple:
        """最終統合レビュー"""
        items = []
        issues = []
        suggestions = []
        
        # 全ステージの結果を集約
        for stage in self.STAGES[:-1]:  # FINAL以外
            review = self._reviews.get(stage)
            if review:
                if review.issues:
                    issues.extend([f"[{stage.value}] {i}" for i in review.issues])
                
                # 未承認チェック
                if not review.approved and review.revision_requested:
                    issues.append(f"[{stage.value}] 修正が未完了です")
        
        # 品質スコア
        # **未計測を「0.0点・不合格」という測定結果に見せない**（R1.5-C4）。
        # この経路（`backend/core/context.py:67`）に品質ゲートは繋がっておらず、
        # dataclass の既定値 0.0 がそのまま「0.0/100・不合格」として出ていた。
        # `report_generator_plugin` で直したのと同じ経路の取りこぼし。
        # **値ではなく旗で判定する**（R1.5-C4・10周目 N-3）。
        # ここは `PipelineContext` 側で 9周目に直したのと同じ形。
        # 値で見ると「測って 0 点」と「未計測」が区別できず、
        # **1ファイル隣に同じ欠陥が残る**（4回踏んだ型）。
        quality_score = context.quality_score
        採点した = (getattr(context, "quality_scored", False)
                    and isinstance(quality_score, (int, float)))
        if not 採点した:
            items.append(ReviewItem(
                id="quality_score",
                type="quality",
                content="品質スコア: **未計測**（この経路に品質ゲートは繋がっていません）",
                # **合否を主張しない。** `measured: False` の項目は
                # 合格数の集計から外れる（`_review_stage`）
                passed=True,
                metadata={"score": None, "measured": False}
            ))
        else:
            items.append(ReviewItem(
                id="quality_score",
                type="quality",
                content=f"品質スコア: {quality_score:.1f}/100",
                passed=quality_score >= 90,
                metadata={"score": quality_score, "measured": True}
            ))
        
        # BGM
        music = context.get_extension("music_layer")
        if music:
            items.append(ReviewItem(
                id="bgm",
                type="bgm",
                content=Path(music).name if music else "未設定",
                passed=bool(music)
            ))
        
        # **1つも測れていないのに「全部パスしました」と言わない**（R1.5-C4）。
        測った = [i for i in items if i.metadata.get("measured") is not False]
        if not issues and 測った:
            suggestions.append("全チェック項目をパスしました！レンダリング準備完了です")
        if items and not 測った:
            suggestions.append(
                "**このステージでは何も測れていません。**"
                "品質ゲートが繋がっていないため、合否を判定できません")
        
        return items, issues, suggestions
    
    def _calculate_consistency(self, items: List[ReviewItem], _stage: ReviewStage) -> float:
        """一貫性スコアを計算"""
        if not items:
            return 100.0
        
        # 問題がある項目の割合から計算
        issue_count = sum(len(item.issues) for item in items)
        max_issues = len(items) * 3  # 1項目最大3問題と仮定
        
        return max(0, 100 - (issue_count / max_issues * 100))
    
    def _get_safe_link(self, path_str: str) -> str:
        """パス文字列をfile:///スキーマに変換し、安全にエンコードしたURLを返す"""
        from urllib.parse import quote
        import os
        
        path_str = path_str.replace(os.path.sep, "/")
        
        if path_str.startswith("file:///"):
            p_clean = path_str[8:]
        elif path_str.startswith("file://"):
            p_clean = path_str[7:]
        else:
            p_clean = path_str
            
        encoded_path = quote(p_clean, safe="/:@!$&'()+,;=-._~")
        
        if ":" in p_clean or p_clean.startswith("/"):
            return "file:///" + encoded_path
        else:
            return "file:///" + encoded_path

    def _format_carousel_items(self, items: List[ReviewItem]) -> List[str]:
        """プレビュー画像がある項目をカルーセル形式でフォーマット"""
        lines = []
        preview_items = [i for i in items if i.preview_path or i.preview_data]
        if preview_items:
            lines.append("````carousel")
            for i, item in enumerate(preview_items):
                if item.preview_path:
                    safe_path = self._get_safe_link(item.preview_path)
                    lines.append(f"![{item.content or item.id}]({safe_path})")
                elif item.preview_data and isinstance(item.preview_data, str) and item.preview_data.startswith("data:"):
                    lines.append(f"![{item.content or item.id}]({item.preview_data})")
                
                if item.issues:
                    lines.append(f"\n⚠️ {', '.join(item.issues)}")
                
                if i < len(preview_items) - 1:
                    lines.append("<!-- slide -->")
            lines.append("````\n")
        return lines

    def _format_text_table_items(self, items: List[ReviewItem]) -> List[str]:
        """テキスト項目を表形式でフォーマット"""
        lines = []
        text_items = [i for i in items if not (i.preview_path or i.preview_data)]
        if text_items:
            lines.append("| ID | 内容 | 状態 | 問題 |")
            lines.append("|:---|:---|:---|:---|")
            for item in text_items[:20]:  # 最大20件
                if item.metadata.get("measured") is False:
                    status = "—"      # 測っていない。合否を主張しない
                else:
                    status = "✅" if item.passed else "⚠️"
                issues = ", ".join(item.issues) if item.issues else "-"
                content = (item.content or "-")[:30]
                lines.append(f"| {item.id} | {content} | {status} | {issues} |")
            lines.append("")
        return lines

    def _format_stage_report(self, review: StageReview) -> str:
        """ステージレポートをMarkdown形式でフォーマット"""
        lines = []
        
        stage_name = self.STAGE_NAMES.get(review.stage, review.stage.value)
        lines.append(f"# 📋 {stage_name}\n")
        lines.append(f"> 生成日時: {review.timestamp}")
        lines.append(f"> ステージ: {review.stage.value}\n")
        
        # スコア
        lines.append("## 📊 スコア\n")
        lines.append(f"| 指標 | スコア |")
        lines.append("|:---|:---|")
        if review.overall_score is None:
            # **測っていないことを点数で表さない**（R1.5-C4）
            lines.append("| 全体スコア | **未計測**（測った項目がありません）|")
        else:
            lines.append(f"| 全体スコア | **{review.overall_score:.1f}**/100 |")
        lines.append(f"| 統一感スコア | **{review.consistency_score:.1f}**/100 |\n")
        
        # 項目一覧
        if review.items:
            lines.append("## 🖼️ レビュー項目\n")
            lines.extend(self._format_carousel_items(review.items))
            lines.extend(self._format_text_table_items(review.items))
        
        # 問題点
        if review.issues:
            lines.append("## ⚠️ 検出された問題\n")
            for issue in review.issues:
                lines.append(f"- {issue}")
            lines.append("")
        
        # 提案
        if review.suggestions:
            lines.append("## 💡 改善提案\n")
            for sug in review.suggestions:
                lines.append(f"- {sug}")
            lines.append("")
        
        # アクション
        lines.append("## 🎯 アクション\n")
        lines.append("以下のオプションを選択してください:\n")
        lines.append("- **[承認]** - このステージを承認して次へ進む")
        lines.append("- **[修正指示]** - 修正内容を指定して再生成")
        lines.append("- **[スキップ]** - 問題を保留して次へ進む\n")
        
        return "\n".join(lines)
    
    def _generate_summary(self, context: ProductionContext) -> Dict[str, Any]:
        """全ステージのサマリーを生成"""
        return {
            "total_stages": len(self.STAGES),
            "completed_stages": len(self._reviews),
            "approved_stages": sum(1 for r in self._reviews.values() if r.approved),
            "pending_revisions": sum(1 for r in self._reviews.values() if r.revision_requested),
            # **未計測のステージを 0 や 100 として平均に混ぜない**（R1.5-C4）
            "overall_score": (
                sum(s for s in _測ったスコア(self._reviews) ) / len(_測ったスコア(self._reviews))
                if _測ったスコア(self._reviews) else None),
            # **`overall_score` の出所が読めるようにする**（R1.5-C4）。
            # `None` = 見るものはあったが測れなかった。
            # `empty` = そもそも見るものが無い（点は 100.0 だが中身は無い）。
            # これを書かないと「100.0」が品質の主張に読める
            "unmeasured_stages": [
                stage.value for stage, r in self._reviews.items()
                if r.overall_score is None],
            "empty_stages": [
                stage.value for stage, r in self._reviews.items()
                if not r.items],
            "scored_stages": [
                stage.value for stage, r in self._reviews.items()
                if r.items and r.overall_score is not None],
            "stages": {
                stage.value: {
                    "name": self.STAGE_NAMES.get(stage),
                    "score": self._reviews[stage].overall_score if stage in self._reviews else None,
                    "approved": self._reviews[stage].approved if stage in self._reviews else False
                }
                for stage in self.STAGES
            }
        }
    
    def approve_stage(self, stage: ReviewStage) -> bool:
        """ステージを承認"""
        if stage in self._reviews:
            self._reviews[stage].approved = True
            self._reviews[stage].revision_requested = False
            return True
        return False
    
    def request_revision(self, stage: ReviewStage, notes: str) -> bool:
        """修正を要求"""
        if stage in self._reviews:
            self._reviews[stage].revision_requested = True
            self._reviews[stage].revision_notes = notes
            self._reviews[stage].approved = False
            return True
        return False
    
    def get_pending_stages(self) -> List[ReviewStage]:
        """未承認ステージを取得"""
        return [
            stage for stage in self.STAGES
            if stage in self._reviews and not self._reviews[stage].approved
        ]
    
    def can_execute(self, context: ProductionContext) -> bool:
        """実行可能かチェック"""
        return True


# シングルトンインスタンス
progressive_review = ProgressiveReviewPlugin()
