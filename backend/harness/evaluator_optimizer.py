"""
evaluator_optimizer.py — Anthropic推奨 Evaluator-Optimizer ワークフロー

既存の品質改善ループ（_quality_improvement_loop）を
Anthropic推奨の「Evaluator-Optimizer」パターンに進化。

既存パターン（Before）:
  Preview再生成 → QualityGate再チェック → ループ
  → ハードコードされたルールベース評価
  → フィードバックが蓄積されるが改善に活用されない

新パターン（After）:
  Evaluator（品質診断） → Optimizer（改善戦略） → 実行 → 再評価 → ループ
  → 構造化されたフィードバック分析
  → 改善アクションの優先度付け
  → パイプラインコンテキストへの改善指示注入
  → 改善効果の定量的追跡

設計思想:
  Anthropic "Building Effective Agents" — Evaluator-Optimizer:
  "One LLM call generates a response while another provides
   evaluation and feedback in a loop."
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# データ構造
# ============================================================

@dataclass
class QualityDiagnosis:
    """Evaluator の診断結果"""
    score: int
    rank: str  # S/A/B/C
    passed: bool
    # 構造化フィードバック
    issues: List[Dict[str, Any]] = field(default_factory=list)
    # カテゴリ別スコア
    category_scores: Dict[str, int] = field(default_factory=dict)
    # 改善可能性の評価
    improvable: bool = True
    improvement_potential: int = 0  # 改善余地（推定ポイント）


@dataclass
class ImprovementAction:
    """Optimizer の改善アクション"""
    action_id: str
    category: str  # "audio", "subtitle", "structure", "metadata"
    description: str
    priority: int  # 1=高, 2=中, 3=低
    estimated_gain: int  # 推定改善ポイント
    executable: bool = True  # 自動実行可能か


@dataclass
class ImprovementPlan:
    """Optimizer の改善計画"""
    actions: List[ImprovementAction] = field(default_factory=list)
    total_estimated_gain: int = 0
    strategy: str = ""  # 改善戦略の説明


@dataclass
class OptimizationResult:
    """改善サイクル全体の結果"""
    initial_score: int
    final_score: int
    iterations: int
    improvements_applied: List[str] = field(default_factory=list)
    diagnosis_history: List[QualityDiagnosis] = field(default_factory=list)
    success: bool = False
    duration_seconds: float = 0.0


# ============================================================
# Evaluator — 品質診断エージェント
# ============================================================

class QualityEvaluator:
    """
    品質診断エージェント。

    既存の QualityGateWorker の結果を構造化し、
    改善可能性と優先度を分析する。

    Anthropicパターン: "One LLM call generates a response"
    → ここではルールベース + 品質プラグインの結果を構造化。
    """

    # 品質カテゴリとその重要度（配点）
    CATEGORY_WEIGHTS = {
        "file_integrity": 20,    # ファイル整合性
        "audio_quality": 20,     # 音声品質
        "subtitle_accuracy": 20, # 字幕精度
        "structure_balance": 15, # 構成バランス
        "metadata_quality": 15,  # メタデータ品質
        "technical_specs": 10,   # 技術仕様
    }

    def evaluate(self, quality_result: Dict, ctx: Any) -> QualityDiagnosis:
        """
        品質結果を診断し、構造化フィードバックを生成。

        Args:
            quality_result: QualityGateWorker の実行結果
            ctx: PipelineContext

        Returns:
            QualityDiagnosis
        """
        score = quality_result.get("score", 0)
        rank = quality_result.get("rank", "C")
        feedback = quality_result.get("feedback", [])
        category_scores = quality_result.get("category_scores", {})

        # フィードバックを構造化
        issues = self._classify_issues(feedback, category_scores)

        # 改善可能性の分析
        improvable_issues = [i for i in issues if i.get("improvable", False)]
        improvement_potential = sum(
            i.get("estimated_gain", 0) for i in improvable_issues
        )

        passed = score >= 90

        diagnosis = QualityDiagnosis(
            score=score,
            rank=rank,
            passed=passed,
            issues=issues,
            category_scores=category_scores,
            improvable=len(improvable_issues) > 0,
            improvement_potential=min(improvement_potential, 100 - score),
        )

        logger.info(
            f"📋 Evaluator診断: {score}点 "
            f"({'合格' if passed else '不合格'}) "
            f"改善余地: +{diagnosis.improvement_potential}pt "
            f"({len(improvable_issues)}件の改善可能項目)"
        )

        return diagnosis

    def _classify_issues(
        self,
        feedback: List[str],
        category_scores: Dict,
    ) -> List[Dict]:
        """フィードバックをカテゴリ別に分類し、改善可能性を付与"""
        issues = []
        # カテゴリ別の改善マッピング
        improvement_map = {
            "audio": {
                "keywords": ["音声", "ラウドネス", "LUFS", "音量", "サイレント"],
                "improvable": True,
                "action": "audio_normalization",
                "estimated_gain": 10,
            },
            "subtitle": {
                "keywords": ["字幕", "テキスト", "校閲", "固有名詞", "誤字"],
                "improvable": True,
                "action": "re_proofread",
                "estimated_gain": 8,
            },
            "structure": {
                "keywords": ["構成", "セグメント", "尺", "バランス", "冗長"],
                "improvable": True,
                "action": "restructure_segments",
                "estimated_gain": 12,
            },
            "metadata": {
                "keywords": ["メタデータ", "タイトル", "タグ", "説明", "チャプター"],
                "improvable": True,
                "action": "regenerate_metadata",
                "estimated_gain": 5,
            },
            "file": {
                "keywords": ["ファイル", "サイズ", "存在", "パス", "フォーマット"],
                "improvable": False,
                "action": "manual_fix",
                "estimated_gain": 0,
            },
            "thumbnail": {
                "keywords": ["サムネイル", "画像", "解像度", "アスペクト比", "ファイルサイズ", "Pillow", "破損"],
                "improvable": True,
                "action": "thumbnail_optimize",
                "estimated_gain": 15,
            },
        }

        for fb in feedback:
            category = "unknown"
            improvable = False
            action = "manual_review"
            estimated_gain = 0

            for cat_name, cat_info in improvement_map.items():
                if any(kw in fb for kw in cat_info["keywords"]):
                    category = cat_name
                    improvable = cat_info["improvable"]
                    action = cat_info["action"]
                    estimated_gain = cat_info["estimated_gain"]
                    break

            issues.append({
                "feedback": fb,
                "category": category,
                "improvable": improvable,
                "action": action,
                "estimated_gain": estimated_gain,
            })

        # カテゴリスコアからも問題を検出
        for cat, score in category_scores.items():
            if score < 70:  # 70点未満のカテゴリは要改善
                cat_key = cat.lower().replace(" ", "_")
                for map_key, map_info in improvement_map.items():
                    if map_key in cat_key:
                        issues.append({
                            "feedback": f"{cat} スコア低下: {score}点",
                            "category": map_key,
                            "improvable": map_info["improvable"],
                            "action": map_info["action"],
                            "estimated_gain": map_info["estimated_gain"],
                        })
                        break

        return issues


# ============================================================
# Optimizer — 改善戦略エージェント
# ============================================================

class QualityOptimizer:
    """
    改善戦略エージェント。

    Evaluator の診断結果から、最も効果的な改善アクションを
    優先度順に提案する。

    Anthropicパターン: "Another provides evaluation and feedback"
    → 改善戦略を構造化し、実行可能なアクションに変換。
    """

    # 利用可能な改善アクション定義
    AVAILABLE_ACTIONS = {
        "audio_normalization": {
            "category": "audio",
            "description": "音声ラウドネスを YouTube 推奨値 (-16 LUFS) に正規化",
            "priority": 1,
            "estimated_gain": 10,
            "executable": True,
        },
        "re_proofread": {
            "category": "subtitle",
            "description": "固有名詞辞書の強化と AI 再校閲",
            "priority": 2,
            "estimated_gain": 8,
            "executable": True,
        },
        "restructure_segments": {
            "category": "structure",
            "description": "冗長セグメントの除去と構成バランス調整",
            "priority": 2,
            "estimated_gain": 12,
            "executable": True,
        },
        "regenerate_metadata": {
            "category": "metadata",
            "description": "AI によるメタデータ再生成（タイトル/説明/タグ/チャプター）",
            "priority": 3,
            "estimated_gain": 5,
            "executable": True,
        },
        "manual_fix": {
            "category": "file",
            "description": "ファイル整合性の手動修復が必要",
            "priority": 1,
            "estimated_gain": 0,
            "executable": False,
        },
        "thumbnail_optimize": {
            "category": "thumbnail",
            "description": "サムネイル画像の再生成および画像処理（解像度・アスペクト比・ファイルサイズ・破損対策の最適化）",
            "priority": 1,
            "estimated_gain": 15,
            "executable": True,
        },
    }

    def plan(self, diagnosis: QualityDiagnosis) -> ImprovementPlan:
        """
        診断結果から改善計画を生成。

        戦略:
        1. 改善可能な issue を estimated_gain 降順でソート
        2. 同一アクションの重複を除去
        3. 合計改善ポイントで合格ラインに到達可能か判定
        """
        if diagnosis.passed:
            return ImprovementPlan(strategy="合格済み — 改善不要")

        # ユニークなアクションを抽出（重複除去）
        seen_actions = set()
        actions = []

        for issue in sorted(
            diagnosis.issues,
            key=lambda i: i.get("estimated_gain", 0),
            reverse=True,
        ):
            action_id = issue.get("action", "manual_review")
            if action_id in seen_actions:
                continue
            if not issue.get("improvable", False):
                continue

            seen_actions.add(action_id)
            action_def = self.AVAILABLE_ACTIONS.get(action_id, {})

            actions.append(ImprovementAction(
                action_id=action_id,
                category=action_def.get("category", issue.get("category", "unknown")),
                description=action_def.get("description", issue.get("feedback", "")),
                priority=action_def.get("priority", 3),
                estimated_gain=action_def.get("estimated_gain", issue.get("estimated_gain", 0)),
                executable=action_def.get("executable", True),
            ))

        # 優先度でソート
        actions.sort(key=lambda a: (a.priority, -a.estimated_gain))

        total_gain = sum(a.estimated_gain for a in actions)
        needed = 90 - diagnosis.score
        can_pass = total_gain >= needed

        strategy = (
            f"現在 {diagnosis.score}点 → 目標 90点（必要: +{needed}pt）。\n"
            f"{'✅' if can_pass else '⚠️'} "
            f"推定改善: +{total_gain}pt "
            f"({'合格到達可能' if can_pass else '合格到達困難 — 最善を尽くす'})。\n"
            f"改善アクション: {len(actions)}件"
        )

        plan = ImprovementPlan(
            actions=actions,
            total_estimated_gain=total_gain,
            strategy=strategy,
        )

        logger.info(f"📋 Optimizer計画: {strategy}")
        return plan


# ============================================================
# Executor — 改善アクション実行
# ============================================================

class ImprovementExecutor:
    """
    改善アクションを実行するエグゼキュータ。

    Optimizer の計画に基づき、パイプラインコンテキストを改善。
    各アクションは既存の Worker を再利用する。
    """

    async def execute_action(
        self,
        action: ImprovementAction,
        ctx: Any,
    ) -> bool:
        """
        単一の改善アクションを実行。

        Returns:
            True if action was applied successfully
        """
        handler = self._action_handlers.get(action.action_id)
        if not handler:
            logger.warning(f"未知のアクション: {action.action_id}")
            return False

        try:
            return await handler(self, ctx)
        except ImportError as e:
            logger.warning(f"必要なモジュールのインポートに失敗しました [{action.action_id}]: {e}")
            return False
        except (ValueError, KeyError, AttributeError, TypeError, OSError, RuntimeError) as e:
            logger.error(f"改善アクション実行中に予期せぬエラーが発生しました [{action.action_id}]: {e}", exc_info=True)
            return False

    async def _action_audio_normalization(self, ctx: Any) -> bool:
        """音声ラウドネス正規化"""
        if not ctx.preview_path or not Path(ctx.preview_path).exists():
            return False

        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg

            if not ffmpeg.is_available():
                return False

            import shutil
            temp_path = ctx.preview_path + ".norm.mp4"
            cmd = [
                "-y", "-i", ctx.preview_path,
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                temp_path,
            ]
            success, _ = ffmpeg.run_command(cmd, timeout=600)
            if success and Path(temp_path).exists():
                shutil.move(temp_path, ctx.preview_path)
                logger.info("🎚️ Optimizer: 音声ラウドネス正規化適用")
                return True
            if Path(temp_path).exists():
                Path(temp_path).unlink()
        except (ImportError, Exception) as e:
            logger.debug(f"Audio normalization skipped: {e}")

        return False

    async def _action_re_proofread(self, ctx: Any) -> bool:
        """AI 再校閲"""
        if not ctx.segments:
            return False

        try:
            from proper_noun_dict import apply_dictionary
            corrections = 0
            for seg in ctx.segments:
                corrected, corr_list = apply_dictionary(seg.get("text", ""))
                if corr_list:
                    seg["text"] = corrected
                    corrections += len(corr_list)

            if corrections > 0:
                logger.info(f"📝 Optimizer: 再校閲 {corrections}件修正")
                return True
        except (ImportError, Exception) as e:
            logger.debug(f"Re-proofread skipped: {e}")

        return False

    async def _action_restructure_segments(self, ctx: Any) -> bool:
        """セグメント構成の最適化"""
        if not ctx.selected_segments:
            return False

        original_count = len(ctx.selected_segments)

        # 短すぎるセグメント（1秒未満）を除去
        filtered = [
            s for s in ctx.selected_segments
            if (s.get("end", 0) - s.get("start", 0)) >= 1.0
        ]

        # テキストが空のセグメントを除去
        filtered = [s for s in filtered if s.get("text", "").strip()]

        removed = original_count - len(filtered)
        if removed > 0:
            ctx.selected_segments = filtered
            logger.info(f"✂️ Optimizer: {removed}セグメント除去（短尺/空テキスト）")
            return True

        return False

    async def _action_regenerate_metadata(self, ctx: Any) -> bool:
        """メタデータ再生成"""
        try:
            from agents.pipeline_coordinator import YouTubeOptWorker
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)
            if result.success:
                logger.info("📊 Optimizer: メタデータ再生成完了")
                return True
        except (ImportError, Exception) as e:
            logger.debug(f"Metadata regeneration skipped: {e}")

        return False

    async def _action_thumbnail_optimize(self, ctx: Any) -> bool:
        """サムネイル画像の再生成・最適化"""
        thumb_path = getattr(ctx, "thumbnail_path", None)
        if not thumb_path and hasattr(ctx, "metadata") and isinstance(ctx.metadata, dict):
            thumb_path = ctx.metadata.get("thumbnail_path")

        if not thumb_path:
            logger.warning("thumbnail_optimize: サムネイルパスが設定されていません")
            return False

        path = Path(thumb_path)
        try:
            from PIL import Image

            if not path.exists():
                logger.info(f"thumbnail_optimize: ファイルが存在しないため新規作成します: {path}")
                path.parent.mkdir(parents=True, exist_ok=True)
                img = Image.new("RGB", (1280, 720), color=(73, 109, 137))
                img.save(path, format="PNG")
            else:
                with Image.open(path) as img:
                    width, height = img.size
                    aspect_ratio = width / height
                    target_ratio = 16.0 / 9.0

                    needs_resize = (width < 1280 or height < 720 or abs(aspect_ratio - target_ratio) > 0.01)

                    if needs_resize:
                        logger.info(f"thumbnail_optimize: 画像をリサイズします。元サイズ: {width}x{height}")
                        if abs(aspect_ratio - target_ratio) > 0.01:
                            if aspect_ratio > target_ratio:
                                new_width = int(height * target_ratio)
                                left = (width - new_width) // 2
                                img = img.crop((left, 0, left + new_width, height))
                            else:
                                new_height = int(width / target_ratio)
                                top = (height - new_height) // 2
                                img = img.crop((0, top, width, top + new_height))
                        img = img.resize((1280, 720), Image.Resampling.LANCZOS)

                    temp_path = path.with_suffix(f".opt.tmp")
                    size_ok = False

                    img.save(temp_path, format="PNG")
                    size_bytes = temp_path.stat().st_size
                    if size_bytes < 4 * 1024 * 1024:
                        size_ok = True
                    else:
                        for quality in [90, 80, 70, 60]:
                            temp_path.unlink(missing_ok=True)
                            img.convert("RGB").save(temp_path, format="JPEG", quality=quality)
                            size_bytes = temp_path.stat().st_size
                            if size_bytes < 4 * 1024 * 1024:
                                size_ok = True
                                break

                    if size_ok:
                        if path.exists():
                            path.unlink()
                        temp_path.rename(path)
                        logger.info(f"thumbnail_optimize: サムネイル最適化に成功しました: {path.name}")
                        return True
                    else:
                        if temp_path.exists():
                            temp_path.unlink()
                        logger.error("thumbnail_optimize: 4MB未満に圧縮できませんでした")
                        return False
            return True
        except (OSError, ValueError) as e:
            logger.error(f"thumbnail_optimize: エラーが発生しました: {e}", exc_info=True)
            return False

    # アクション → ハンドラのマッピング
    _action_handlers = {
        "audio_normalization": _action_audio_normalization,
        "re_proofread": _action_re_proofread,
        "restructure_segments": _action_restructure_segments,
        "regenerate_metadata": _action_regenerate_metadata,
        "thumbnail_optimize": _action_thumbnail_optimize,
    }


# ============================================================
# EvaluatorOptimizer — ワークフロー全体
# ============================================================

class EvaluatorOptimizerWorkflow:
    """
    Anthropic推奨 Evaluator-Optimizer ワークフロー。

    既存の _quality_improvement_loop を完全に置き換え、
    構造化された改善サイクルを実装。

    フロー:
    1. Evaluate: 品質診断（構造化フィードバック生成）
    2. Plan: 改善計画策定（優先度付きアクション）
    3. Execute: 改善アクション実行
    4. Re-evaluate: 品質再チェック
    5. Repeat: 合格まで or 上限回数まで

    Usage:
        from harness.evaluator_optimizer import evaluator_optimizer

        result = await evaluator_optimizer.run(ctx, max_iterations=3)
        print(f"Score: {result.initial_score} → {result.final_score}")
    """

    MAX_ITERATIONS = 3

    def __init__(self):
        self.evaluator = QualityEvaluator()
        self.optimizer = QualityOptimizer()
        self.executor = ImprovementExecutor()

    async def run(
        self,
        ctx: Any,
        max_iterations: Optional[int] = None,
    ) -> OptimizationResult:
        """
        Evaluator-Optimizer ループを実行。

        Args:
            ctx: PipelineContext
            max_iterations: 最大イテレーション数

        Returns:
            OptimizationResult
        """
        max_iter = max_iterations or self.MAX_ITERATIONS
        start_time = time.time()

        # 初回評価
        initial_quality = await self._run_quality_check(ctx)
        initial_score = initial_quality.get("score", 0)

        result = OptimizationResult(
            initial_score=initial_score,
            final_score=initial_score,
            iterations=0,
        )

        # 初回診断
        diagnosis = self.evaluator.evaluate(initial_quality, ctx)
        result.diagnosis_history.append(diagnosis)

        if diagnosis.passed:
            result.success = True
            result.duration_seconds = round(time.time() - start_time, 1)
            logger.info(f"✅ 初回評価で合格: {initial_score}点")
            return result

        # 改善ループ
        for iteration in range(1, max_iter + 1):
            result.iterations = iteration

            logger.info(
                f"🔄 改善イテレーション {iteration}/{max_iter}: "
                f"現在 {diagnosis.score}点"
            )

            # Step 1: 改善計画
            plan = self.optimizer.plan(diagnosis)

            if not plan.actions:
                logger.warning("改善可能なアクションなし — ループ終了")
                break

            # Step 2: アクション実行
            for action in plan.actions:
                if not action.executable:
                    continue

                success = await self.executor.execute_action(action, ctx)
                if success:
                    result.improvements_applied.append(
                        f"[iter{iteration}] {action.description}"
                    )

            # Step 3: プレビュー再生成（改善適用後）
            await self._regenerate_preview(ctx)

            # Step 4: 再評価
            quality = await self._run_quality_check(ctx)
            diagnosis = self.evaluator.evaluate(quality, ctx)
            result.diagnosis_history.append(diagnosis)
            result.final_score = diagnosis.score

            if diagnosis.passed:
                result.success = True
                logger.info(
                    f"✅ 品質改善成功: {initial_score}点 → {diagnosis.score}点 "
                    f"({iteration}回目のイテレーション)"
                )
                break

            # 改善が見込めない場合は早期終了
            if not diagnosis.improvable:
                logger.warning("改善余地なし — ループ終了")
                break

            # スコアが下がった場合も終了
            if diagnosis.score < result.diagnosis_history[-2].score:
                logger.warning(
                    f"スコア悪化検出: {result.diagnosis_history[-2].score} → {diagnosis.score} "
                    f"— ループ終了"
                )
                break

        result.duration_seconds = round(time.time() - start_time, 1)

        if not result.success:
            logger.warning(
                f"⚠️ 改善ループ完了（不合格のまま）: "
                f"{initial_score}点 → {result.final_score}点 "
                f"({result.iterations}回)"
            )

        return result

    async def _run_quality_check(self, ctx: Any) -> Dict:
        """品質チェックを実行"""
        try:
            from agents.pipeline_coordinator import QualityGateWorker
            worker = QualityGateWorker()
            result = await worker.execute(ctx)
            return result.data
        except ImportError as e:
            logger.error(f"QualityGateWorker のインポートに失敗しました: {e}")
            return {"score": 0, "rank": "C", "feedback": [f"ImportError: {e}"]}
        except (ValueError, KeyError, AttributeError, TypeError, OSError, RuntimeError) as e:
            logger.error(f"品質チェック実行中に予期せぬエラーが発生しました: {e}", exc_info=True)
            return {"score": 0, "rank": "C", "feedback": [str(e)]}

    async def _regenerate_preview(self, ctx: Any) -> bool:
        """プレビューを再生成"""
        try:
            from agents.pipeline_coordinator import PreviewWorker
            worker = PreviewWorker()
            result = await worker.execute(ctx)
            return result.success
        except ImportError as e:
            logger.warning(f"PreviewWorker のインポートに失敗しました: {e}")
            return False
        except (ValueError, KeyError, AttributeError, TypeError, OSError, RuntimeError) as e:
            logger.error(f"プレビュー再生成中に予期せぬエラーが発生しました: {e}", exc_info=True)
            return False


# ============================================================
# OrchestratorEvaluatorOptimizer — 運行管理連動（Stage 3）
# ============================================================

class OrchestratorEvaluatorOptimizer:
    """
    Orchestration 監査ログ（harness_audit_log.jsonl）および
    バッチ実行レポートから開発プロセスのボトルネックを分析し、
    自律的に design_stock.json に対し改善案を pending 登録する。
    """

    def analyze_and_suggest(
        self,
        batch_id: str,
        results: dict,
        report: dict,
        store_path: Optional[str] = None,
    ) -> None:
        """
        バッチ報告結果を基にボトルネックを診断し、必要に応じて設計ストックを追加。
        """
        logger.info(f"🔍 [Stage 3] ボトネック分析開始: batch={batch_id}")

        suggestions = []
        # 1. 失敗タスクの検知
        suggestions.extend(self._detect_failures(results, batch_id))
        # 2. 大規模変更ファイルの検知
        suggestions.extend(self._detect_heavy_changes(report, batch_id))
        # 3. カバレッジ不足の検知
        suggestions.extend(self._detect_coverage_debt(batch_id))

        if not suggestions:
            logger.info("🟢 [Stage 3] ボトルネックは検出されませんでした。")
            return

        # 提案の登録
        for sug in suggestions:
            try:
                self._register_suggested_stock(
                    title=sug["title"],
                    difficulty=sug["difficulty"],
                    description=sug["description"],
                    source=sug["source"],
                    store_path=store_path
                )
            except (OSError, ValueError, TypeError) as e:
                logger.error(f"❌ [Stage 3] 設計ストック起票に失敗しました: {e}", exc_info=True)

    def _detect_failures(self, results: dict, batch_id: str) -> List[Dict]:
        """失敗タスクを検知"""
        failed = results.get("failed", 0)
        if failed > 0:
            return [{
                "title": f"[AUTO-DETECT] バッチ失敗に伴うデバッグと自動改善",
                "difficulty": "C",  # 失敗への対処は低難度としてFlashが即時デバッグ可能に
                "description": f"バッチ {batch_id} において {failed} 件のタスク失敗が検出されました。エラーログの解析と修正、およびデグレード防止テストの強化が必要です。",
                "source": f"Audit Log (failed tasks in {batch_id})"
            }]
        return []

    def _detect_heavy_changes(self, report: dict, batch_id: str) -> List[Dict]:
        """大規模ファイル変更を検知"""
        git_summary = report.get("git_diff_summary", {})
        files_changed = git_summary.get("files_changed", 0)
        
        # 閾値: 15ファイル以上の変更
        if files_changed >= 15:
            return [{
                "title": f"[AUTO-DETECT] 大規模変更タスクのマイクロタスク細分化",
                "difficulty": "B",  # 設計変更と分割方針検討を伴うため中難度
                "description": f"バッチ {batch_id} にて {files_changed} ファイルの大規模な変更が記録されました。変更スコープが肥大化しているため、モジュール分割やタスク細分化（DS-014準拠）によるリファクタリングを推奨します。",
                "source": f"Audit Log (massive files_changed in {batch_id})"
            }]
        return []

    def _detect_coverage_debt(self, batch_id: str) -> List[Dict]:
        """カバレッジ不足を検知"""
        # phase_state.json からカバレッジ情報を読み取る
        try:
            from backend.agents.orchestration.atomic_io import safe_read_json
            from pathlib import Path
            phase_state_path = Path(__file__).resolve().parents[1] / "agents" / "memory" / "phase_state.json"
            if phase_state_path.exists():
                state = safe_read_json(str(phase_state_path), default={})
                coverage = state.get("metrics", {}).get("coverage_pct", 100.0)
                if coverage < 30.0:
                    return [{
                        "title": f"[AUTO-DETECT] 未カバー領域の体系的テスト拡充",
                        "difficulty": "B",  # カバレッジ改善計画（DS-012準拠）に基づくため中難度
                        "description": f"バッチ {batch_id} 完了後のテストカバレッジが {coverage:.2f}% と低水準（30%未満）です。カバレッジ改善規約に基づき、未カバー行（特に直接変更行）に対する体系的なユニットテストの拡充が必要です。",
                        "source": f"Phase State Metrics (low coverage after {batch_id})"
                    }]
        except (ImportError, OSError, ValueError, KeyError) as e:
            logger.warning(f"[Stage 3] カバレッジ測定データの読み込みに失敗しました: {e}")
        return []

    def _register_suggested_stock(
        self,
        title: str,
        difficulty: str,
        description: str,
        source: str,
        store_path: Optional[str] = None,
    ) -> None:
        """重複チェックを行い、新規設計ストックを pending で追加"""
        from backend.agents.orchestration.design_stock import DesignStockStore
        
        # テスト実行中でダッシュボード汚染を防ぐ設定
        import sys
        if "pytest" in sys.modules and not store_path:
            logger.info(f"Pytest run detected. Skipping real design_stock.json write for '{title}' to prevent pollution.")
            return

        store = DesignStockStore(path=store_path)
        
        # 重複チェック
        for item in store.items:
            if item["title"] == title and item["status"] in ("pending", "in_discussion", "designed", "dispatched"):
                logger.info(f"⏭️ [Stage 3] 重複する自動起票ストックが存在するためスキップします: {title} (ID: {item['id']}, status: {item['status']})")
                return

        # 追加
        # 現在のフェーズを取得
        phase = 27
        try:
            from backend.agents.orchestration.atomic_io import safe_read_json
            from pathlib import Path
            phase_state_path = Path(__file__).resolve().parents[1] / "agents" / "memory" / "phase_state.json"
            if phase_state_path.exists():
                state = safe_read_json(str(phase_state_path), default={})
                phase = state.get("current_phase", 27)
        except (ImportError, OSError, ValueError, KeyError, AttributeError):
            pass

        item = store.add_item(
            title=title,
            phase=phase,
            difficulty=difficulty,
            description=description,
            source_phase_task=source
        )
        logger.info(f"🚀 [Stage 3] 自動起票に成功しました: {item['id']} - {title}")


# ============================================================
# シングルトン
# ============================================================
evaluator_optimizer = EvaluatorOptimizerWorkflow()
orchestrator_evaluator_optimizer = OrchestratorEvaluatorOptimizer()
