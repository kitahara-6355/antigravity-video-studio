"""
QualityGateWorker — 品質チェックステージ

プラグインアーキテクチャ版（憲法§3.2準拠）。
チェック項目は quality_gate_plugins.py に独立プラグインとして分離。
"""

import logging
import time
import subprocess
import json
from pathlib import Path

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


class QualityGateWorker(PipelineStageWorker):
    """
    品質ゲート — プラグインアーキテクチャ版（憲法§3.2準拠）。
    
    チェック項目は quality_gate_plugins.py に独立プラグインとして分離。
    モデルチェンジ（フェーズ2-4）はプラグインの追加だけで実現。
    """
    def __init__(self):
        super().__init__("品質チェック", "✅", 5)

    def get_definition_of_done(self) -> str:
        return "品質スコア90点以上かつ致命的エラーゼロ"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """品質チェックを実行

        入力契約:
            ctx.preview_path: Optional[str] — プレビューファイルパス（なくても動作）
            ctx.segments: list[dict] — セグメント情報
            ctx.template_config: Optional[Dict] — テンプレート設定
        出力契約:
            ctx.quality_score: int — 0-100の品質スコア
            ctx.quality_feedback: list[str] — フィードバック項目
            ctx.quality_category_report: list — カテゴリ別レポート
            ctx.quality_category_scores: dict — カテゴリ別スコア
        """
        start = time.time()
        score = 100  # 満点から減点方式
        feedback = []

        # **台帳に載っている「まだ無い機能」を先に知る**（R1.5・2026-08-27）。
        # 既に入っていれば尊重する（テストが差し替えられるように）。
        if not hasattr(ctx, "declared_gaps"):
            try:
                from feature_gaps import declared_capabilities
                ctx.declared_gaps = declared_capabilities()
            except Exception as e:  # noqa: BLE001 — 台帳が読めなくても実行は止めない
                logger.warning(f"⚠️ 実装不足項目の台帳を読めませんでした: {e}")
                ctx.declared_gaps = set()

        # ━━━ META-01修正: FFprobe実測チェック (QualityGate v2) ━━━
        # プラグインチェックの前に、出力動画の物理的整合性を検証
        ffprobe_passed = True
        try:
            ffprobe_result = self._ffprobe_physical_check(ctx)
            for item in ffprobe_result.get("failures", []):
                score -= item["deduction"]
                feedback.append(f"⛔ FFprobe: {item['message']}")
                ffprobe_passed = False
            for item in ffprobe_result.get("warnings", []):
                feedback.append(f"⚠️ FFprobe: {item}")
            if ffprobe_passed:
                logger.info("✅ FFprobe物理検証: 全チェックPASS")
        except subprocess.SubprocessError as e:
            logger.warning(f"FFprobe物理検証スキップ (サブプロセスエラー): {e}")
            feedback.append(f"⚠️ FFprobe検証実行不可: {e}")
        except Exception as e:
            logger.warning(f"FFprobe物理検証スキップ (想定外エラー): {e}", exc_info=True)
            feedback.append(f"⚠️ FFprobe検証実行不可: {e}")
            try:
                from agents.memory.technical_debt import technical_debt_store
                technical_debt_store.register_debt(
                    category="MINOR_INFRA",
                    file_path="backend/agents/workers/quality_gate_worker.py",
                    line_number=66,
                    pattern="except Exception as e: in execute (ffprobe physical check)",
                    cause_pattern="DP-01",
                    fix_pattern="FFprobe物理検証のエラーハンドリングと安全なスキップ",
                    registered_by="bug_hunter_t_1f6ac8",
                    notes=f"FFprobe物理検証実行エラー: {str(e)}",
                )
            except Exception as tdr_err:
                logger.error(f"Failed to register debt for ffprobe check in quality_gate_worker.py: {tdr_err}")

        # ━━━ サムネイル物理チェック ━━━
        # 画像ファイルの実在・サイズ・フォーマット・解像度・アスペクト比などを検証
        thumbnail_passed = True
        try:
            thumb_result = self._thumbnail_physical_check(ctx)
            for item in thumb_result.get("failures", []):
                score -= item["deduction"]
                feedback.append(f"⛔ サムネイル: {item['message']}")
                thumbnail_passed = False
            for item in thumb_result.get("warnings", []):
                feedback.append(f"⚠️ サムネイル: {item}")
            if thumbnail_passed:
                logger.info("✅ サムネイル物理検証: 全チェックPASS")
        except Exception as e:
            logger.warning(f"サムネイル物理検証スキップ (想定外エラー): {e}", exc_info=True)
            feedback.append(f"⚠️ サムネイル検証実行不可: {e}")
            try:
                from agents.memory.technical_debt import technical_debt_store
                technical_debt_store.register_debt(
                    category="MINOR_INFRA",
                    file_path="backend/agents/workers/quality_gate_worker.py",
                    line_number=88,
                    pattern="except Exception as e: in execute (thumbnail physical check)",
                    cause_pattern="DP-01",
                    fix_pattern="サムネイル物理検証のエラーハンドリングと安全なスキップ",
                    registered_by="bug_hunter_t_1f6ac8",
                    notes=f"サムネイル物理検証実行エラー: {str(e)}",
                )
            except Exception as tdr_err:
                logger.error(f"Failed to register debt for thumbnail check in quality_gate_worker.py: {tdr_err}")

        # プラグインエンジンに委譲
        run_all_plugins = None
        try:
            from quality_gate_plugins import run_all_plugins
        except ImportError:
            logger.warning("quality_gate_plugins not found — basic check only")

        if run_all_plugins is not None:
            try:
                from template_config import template_config as _tc
            except (ImportError, SyntaxError) as e:
                logger.warning(f"template_configのインポート失敗 (basicフォールバックします): {e}")
                _tc = None
                try:
                    from agents.memory.technical_debt import technical_debt_store
                    technical_debt_store.register_debt(
                        category="MINOR_INFRA",
                        file_path="backend/agents/workers/quality_gate_worker.py",
                        line_number=126,
                        pattern="except ImportError as e: in execute (template_config import)",
                        cause_pattern="DP-01",
                        fix_pattern="template_configインポート失敗のハンドリングとフォールバック",
                        registered_by="bug_hunter_t_1f6ac8",
                        notes=f"template_configインポートエラー: {str(e)}",
                    )
                except Exception as tdr_err:
                    logger.error(f"Failed to register debt for template_config import in quality_gate_worker.py: {tdr_err}")
            
            try:
                result = run_all_plugins(ctx, _tc)
                score -= result["total_deductions"]
                feedback.extend(result["feedback"])
            except ImportError:
                # W6-C4-41仕様: ImportErrorはそのまま上流に伝播させる
                raise
            except Exception as e:
                logger.error(f"プラグイン実行中に想定外のエラーが発生しました: {e}", exc_info=True)
                score -= 50
                feedback.append(f"⛔ 品質チェックプラグインのエラー: {e}")
                result = {"total_deductions": 50, "feedback": feedback,
                          "category_report": [], "category_scores": {}}
                try:
                    from agents.memory.technical_debt import technical_debt_store
                    technical_debt_store.register_debt(
                        category="MINOR_INFRA",
                        file_path="backend/agents/workers/quality_gate_worker.py",
                        line_number=96,
                        pattern="except Exception as e: in execute (plugin run)",
                        cause_pattern="DP-01",
                        fix_pattern="プラグインエラーのハンドリングとフォールバック",
                        registered_by="bug_hunter_t_1f6ac8",
                        notes=f"run_all_pluginsの実行エラー: {str(e)}",
                    )
                except Exception as tdr_err:
                    logger.error(f"Failed to register debt in quality_gate_worker.py: {tdr_err}")
        else:
            if ctx.preview_path and Path(ctx.preview_path).exists():
                if Path(ctx.preview_path).stat().st_size < 1024:
                    score -= 30
                    feedback.append("ファイルサイズが異常に小さい")
            else:
                score -= 20
                feedback.append("プレビューファイルが存在しない")
            result = {"total_deductions": 100 - score, "feedback": feedback,
                      "category_report": [], "category_scores": {}}

        # **0で床打ちすると「どれくらい悪いか」が消える**（R1.5・2026-08-27）。
        # 実測では減点合計 -134（素点 -34）でも表示は 0 点で、改善しても数字が
        # 動かなかった（品質改善ループ3周がまったく動かなかった原因の1つ）。
        # `ctx.quality_score` の 0〜100 は消費側が多いので変えない。
        # **素点は捨てずに記録と出力へ回す。**
        raw_score = score
        score = max(0, min(100, score))
        rank = "S" if score >= 95 else "A" if score >= 90 else "B" if score >= 80 else "C"
        ctx.quality_score = score
        # **ここでしか立たない**（R1.5-C4）。0.0 は実際に取りうる点なので、
        # 「測った」を値ではなくこの旗で表す
        ctx.quality_scored = True
        ctx.quality_feedback = feedback
        # **落ちた検査を実行記録に残す**（R1.5-C4・19周目）。
        # `run_all_plugins` の中でプラグインが落ちると、その項目の減点が
        # 消えて**壊れているほど点が上がる**。`quality_scored` は
        # 「採点しようとしたか」の旗なので、「**全項目を検査できたか**」は
        # 別に持つ。ここが無いと「22項目を検査した 95点」と
        # 「3項目が壊れていて残りだけで出た 95点」が区別できない。
        落ちた検査 = result.get("failed_plugins", []) or []
        ctx.quality_gate_report = {
            "raw_score": raw_score,
            "clamped": raw_score != score,
            "deductions": 100 - raw_score,
            "all_plugins_ran": result.get("all_plugins_ran", True),
            "failed_plugins": 落ちた検査,
        }
        # カテゴリ情報を直接ctxに保存（_build_resultで確実に取得するため）
        ctx.quality_category_report = result.get("category_report", [])
        ctx.quality_category_scores = result.get("category_scores", {})

        return StageResult(
            stage_name=self.name, success=score >= 90,
            detail=(f"スコア: {score}点（素点 {raw_score}）(ランク{rank})"
                    if raw_score != score else f"スコア: {score}点 (ランク{rank})"),
            data={
                "score": score, "raw_score": raw_score,
                "rank": rank, "feedback": feedback,
                "category_report": ctx.quality_category_report,
                "category_scores": ctx.quality_category_scores,
                # 画面まで届かせる（R1.5-C4・19周目）
                "all_plugins_ran": result.get("all_plugins_ran", True),
                "failed_plugins": 落ちた検査,
            },
            duration_seconds=round(time.time() - start, 1),
        )

    def _ffprobe_physical_check(self, ctx: PipelineContext) -> dict:
        """FFprobe駆動の物理的整合性チェック (QualityGate v2)

        Returns:
            {"failures": [{"message": str, "deduction": int}], "warnings": [str]}
        """
        import subprocess
        import json as _json

        failures = []
        warnings = []
        preview = ctx.preview_path

        if not preview or not Path(preview).exists():
            return {"failures": [{"message": "プレビューファイルが存在しない", "deduction": 50}],
                    "warnings": []}

        # FFprobeで実測
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", preview],
                capture_output=True, text=True, encoding="utf-8", timeout=30
            )
            if r.returncode != 0:
                err_msg = r.stderr.strip() if r.stderr else f"Exit code {r.returncode}"
                raise subprocess.SubprocessError(f"ffprobe failed: {err_msg}")
        except FileNotFoundError as e:
            raise subprocess.SubprocessError(f"ffprobe command not found: {e}")
        except subprocess.TimeoutExpired as e:
            raise subprocess.SubprocessError(f"ffprobe command timed out after {e.timeout} seconds.")

        try:
            data = _json.loads(r.stdout)
        except _json.JSONDecodeError as je:
            raise ValueError(f"Failed to parse ffprobe output: {je}. Raw output: {r.stdout[:200]}")
        
        if not isinstance(data, dict):
            raise ValueError("ffprobe output is not a JSON object")

        fmt = data.get("format")
        if not isinstance(fmt, dict):
            fmt = {}

        def _safe_float(val, default=0.0) -> float:
            if val is None:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        def _safe_int(val, default=0) -> int:
            if val is None:
                return default
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        actual_duration = _safe_float(fmt.get("duration"))
        actual_size = _safe_int(fmt.get("size"))

        # QV-01: 出力尺 vs 目標尺 (±5分以内)
        target_minutes = getattr(ctx, "target_minutes", 0)
        if target_minutes is None:
            target_minutes = 0
        target_sec = target_minutes * 60

        if target_sec > 0 and actual_duration > 0:
            diff_min = abs(actual_duration - target_sec) / 60
            if diff_min > 5:
                failures.append({
                    "message": f"出力尺異常: {actual_duration/60:.1f}分 (目標{target_minutes}分, 差{diff_min:.1f}分)",
                    "deduction": 50
                })
            elif diff_min > 3:
                warnings.append(f"出力尺やや乖離: {actual_duration/60:.1f}分 (目標{target_minutes}分)")

        # QV-02: 出力尺がRAW合計尺を超えていないか
        # (SmartCutで短くなるべきなのに長くなっていたら明らかなバグ)
        if target_sec > 0 and actual_duration > target_sec * 3:
            failures.append({
                "message": f"出力尺が目標の{actual_duration/target_sec:.1f}倍に膨張 ({actual_duration/60:.1f}分)",
                "deduction": 50
            })

        # QV-04: ファイルサイズ (20分動画なら最低10MB)
        if actual_duration > 300 and actual_size < 10 * 1024 * 1024:
            failures.append({
                "message": f"ファイルサイズ異常: {actual_size/1024/1024:.1f}MB ({actual_duration/60:.1f}分の動画)",
                "deduction": 30
            })

        streams = data.get("streams")
        if not isinstance(streams, list):
            streams = []

        # QV-05: 音声トラック存在チェック
        has_audio = any(isinstance(s, dict) and s.get("codec_type") == "audio" for s in streams)
        if not has_audio:
            failures.append({
                "message": "音声トラックが存在しない",
                "deduction": 40
            })

        # QV-03: 映像ストリーム存在
        has_video = any(isinstance(s, dict) and s.get("codec_type") == "video" for s in streams)
        if not has_video:
            failures.append({
                "message": "映像ストリームが存在しない",
                "deduction": 50
            })

        logger.info(f"🔍 FFprobe検証: duration={actual_duration/60:.1f}min, "
                     f"size={actual_size/1024/1024:.1f}MB, "
                     f"audio={has_audio}, video={has_video}, "
                     f"failures={len(failures)}")

        return {"failures": failures, "warnings": warnings}

    def _thumbnail_physical_check(self, ctx: PipelineContext) -> dict:
        """サムネイル画像の物理的整合性チェック

        Returns:
            {"failures": [{"message": str, "deduction": int}], "warnings": [str]}
        """
        # **本線に無い機能を減点しない**（R1.5・2026-08-27 ユーザー決定）。
        # 本線にサムネイル工程は無いので、減点し続けると品質ゲートは
        # **原理的に閾値へ到達できない**。台帳に載っている間は「やっていない」
        # として `skipped_features` に出す。実装したら台帳から消え、
        # **その瞬間からゲートが本気で見はじめる。**
        if "thumbnail" in getattr(ctx, "declared_gaps", set()):
            未実装 = "サムネイル（未実装）"
            if 未実装 not in ctx.skipped_features:
                ctx.skipped_features.append(未実装)
            return {"failures": [], "warnings": [f"⬜ {未実装}。台帳に載っています"]}

        try:
            from PIL import Image, UnidentifiedImageError
        except ImportError as ie:
            return {"failures": [{"message": f"Pillowライブラリがインストールされていません: {ie}", "deduction": 20}],
                    "warnings": []}
        failures = []
        warnings = []

        thumbnail_path = getattr(ctx, "thumbnail_path", None)
        if not thumbnail_path and hasattr(ctx, "metadata") and isinstance(ctx.metadata, dict):
            thumbnail_path = ctx.metadata.get("thumbnail_path")

        if not thumbnail_path or not isinstance(thumbnail_path, (str, Path)):
            return {"failures": [{"message": "サムネイルパスが設定されていません", "deduction": 20}],
                    "warnings": []}

        path = Path(thumbnail_path)
        if not path.exists():
            return {"failures": [{"message": f"サムネイルファイルが存在しません: {path.name}", "deduction": 20}],
                    "warnings": []}

        size = path.stat().st_size
        if size == 0:
            failures.append({"message": "サムネイルファイルが空です", "deduction": 20})
            return {"failures": failures, "warnings": warnings}
        elif size > 2 * 1024 * 1024:
            failures.append({
                "message": f"サムネイルサイズがYouTube上限(2MB)を超過しています: {size/1024/1024:.1f}MB",
                "deduction": 15
            })

        try:
            with Image.open(path) as img:
                # hasattrは内部でAttributeErrorを握りつぶしてFalseを返すため、
                # 直接プロパティにアクセスして例外ハンドラへ伝播させる。
                # ただし、属性自体が存在しない場合の AttributeError はここでキャッチし、
                # 「サイズ情報が取得できません」として処理する。
                try:
                    size_attr = img.size
                except AttributeError:
                    failures.append({"message": "サムネイル画像のサイズ情報が取得できません", "deduction": 20})
                    return {"failures": failures, "warnings": warnings}

                if not isinstance(size_attr, tuple) or len(size_attr) < 2:
                    failures.append({"message": "サムネイル画像のサイズ情報が取得できません", "deduction": 20})
                    return {"failures": failures, "warnings": warnings}
                
                width, height = size_attr
                fmt = img.format

                if fmt not in ["JPEG", "PNG"]:
                    failures.append({
                        "message": f"非サポートのサムネイルフォーマットです: {fmt} (JPEGまたはPNG推奨)",
                        "deduction": 10
                    })

                if width < 640:
                    failures.append({
                        "message": f"サムネイルの幅が小さすぎます: {width}px (最小640px)",
                        "deduction": 15
                    })

                if height == 0:
                    failures.append({"message": "サムネイル画像の高さが0です", "deduction": 20})
                    return {"failures": failures, "warnings": warnings}

                ratio = width / height
                expected_ratio = 16 / 9
                if abs(ratio - expected_ratio) > 0.05:
                    warnings.append(f"サムネイルのアスペクト比が16:9ではありません (現在 {width}:{height} = {ratio:.2f})")

        except (UnidentifiedImageError, OSError, ValueError, AttributeError) as e:
            failures.append({"message": f"サムネイル画像が破損しているか、読み込めません: {e}", "deduction": 20})

        return {"failures": failures, "warnings": warnings}

    def verify(self, result: StageResult) -> bool:
        return result.data.get("score", 0) >= 90
