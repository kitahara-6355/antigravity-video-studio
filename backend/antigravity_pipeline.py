"""
Antigravity 3.0 統合パイプライン
全Phaseを連携させた統合処理

使用方法:
    python -m backend.antigravity_pipeline <input_srt>
"""

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pipeline_error_strategy import (
    QualityDegradation,
    _log_quality_degradation,
    pipeline_retry,
)

# Phase 1: Foundation
from proper_noun_dict import proper_noun_dict
import proper_noun_dict as proper_noun_dict_module
from subtitle_normalizer import SRTExporter

# Phase 2: Context Intelligence
import semantic_store as semantic_store_module
from semantic_store import SemanticSubtitleStoreV2 as SemanticSubtitleStore

# Phase 3: Generative Proposal
import telop_proposal_engine

# Phase 4: Creative Asset Library
from asset_library import asset_library
import asset_library as asset_lib

# 依存関数のラップ（テストモックの互換性のため）
def apply_dictionary(*args, **kwargs):
    return proper_noun_dict_module.apply_dictionary(*args, **kwargs)

def create_semantic_store(*args, **kwargs):
    return semantic_store_module.create_semantic_store(*args, **kwargs)

def extract_telops(*args, **kwargs):
    return telop_proposal_engine.extract_telops(*args, **kwargs)

def propose_scenes(*args, **kwargs):
    return telop_proposal_engine.propose_scenes(*args, **kwargs)

def get_assets_for(*args, **kwargs):
    return asset_lib.get_assets_for(*args, **kwargs)

# Phase 7: Learning Loop
from learning_loop import learning_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 伝播させるべきプログラムの設計バグやシステム上の例外
PROGRAM_ERRORS = (
    TypeError,
    NameError,
    AttributeError,
    ZeroDivisionError,
    KeyError,
    IndexError,
    ImportError,
    ModuleNotFoundError,
    RecursionError,
    AssertionError,
    MemoryError,
    SystemError,
    FileNotFoundError,
    IsADirectoryError,
    PermissionError,
)


class AntigravityPipeline:
    """Antigravity 3.0 統合パイプライン"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path("output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_srt(self, srt_path: Path) -> Dict:
        """
        SRTファイルを完全処理

        Args:
            srt_path: 入力SRTファイル

        Returns:
            処理結果
        """
        logger.info(f"=== Antigravity 3.0 処理開始 ===")
        logger.info(f"入力: {srt_path}")

        srt_path = Path(srt_path)

        result = {
            "input": str(srt_path),
            "processed_at": datetime.now().isoformat(),
            "phases": {}
        }

        # 致命的チェック: ファイルが存在しないかディレクトリの場合
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")
        if srt_path.is_dir():
            raise IsADirectoryError(f"SRT path is a directory: {srt_path}")

        # Phase 1: 固有名詞辞書適用
        corrected_segments = self._run_phase1_dictionary_application(srt_path, result)

        # Phase 2: Semantic分析
        semantic_store, store_path = self._run_phase2_semantic_analysis(corrected_segments, result)

        # Phase 3: テロップ提案
        telop_candidates, scene_proposals = self._run_phase3_telop_proposal(corrected_segments, result)

        # Phase 4: アセット参照
        self._run_phase4_asset_reference(result)

        # 出力
        logger.info("Phase 5-7: 出力生成中...")

        # SRT出力 & 提案レポート出力
        srt_output, proposal_path = self._export_outputs(
            srt_path, corrected_segments, telop_candidates, scene_proposals, result
        )

        result["outputs"] = {
            "srt": str(srt_output) if srt_output else None,
            "proposals": str(proposal_path) if proposal_path else None,
            "semantic_store": str(store_path) if store_path else None
        }

        logger.info("=== 処理完了 ===")
        logger.info(f"SRT出力: {srt_output}")
        logger.info(f"提案レポート: {proposal_path}")

        # === 品質フィードバックフック: NHKスコアラ自動実行 ===
        try:
            self._run_nhk_quality_scoring(srt_output, result)
        except Exception as e:
            logger.warning(
                "NHK quality scoring in process_srt failed (ignored): %s",
                str(e),
                exc_info=True
            )

        return result

    def _run_phase1_dictionary_application(self, srt_path: Path, result: Dict) -> List[Dict]:
        """Phase 1: 固有名詞辞書を適用"""
        logger.info("Phase 1: 固有名詞辞書を適用中...")
        try:
            segments = self._parse_srt(srt_path)
            if not segments:
                raise ValueError("No valid subtitle segments parsed from SRT.")

            corrected_segments = []
            total_corrections = 0

            for seg in segments:
                if not isinstance(seg, dict):
                    logger.warning("Skipping invalid segment type: %s", type(seg))
                    continue
                text = seg.get("text", "")
                if not isinstance(text, str):
                    logger.warning("Skipping segment with non-string text: %s", type(text))
                    continue
                corrected_text, corrections = apply_dictionary(text)
                seg["text"] = corrected_text
                seg["corrections"] = corrections
                corrected_segments.append(seg)
                total_corrections += len(corrections)

            # 字幕の品質（表示速度・行文字数制限）自動補正
            corrected_segments = self._normalize_subtitles_for_quality(corrected_segments)

            result["phases"]["phase_1"] = {
                "status": "completed",
                "segments": len(corrected_segments),
                "corrections": total_corrections
            }
            logger.info(f"  修正数: {total_corrections}件（品質補正適用済）")
            return corrected_segments
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Phase 1 failed: {e}", exc_info=True)
            _log_quality_degradation(QualityDegradation(
                phase="phase_1",
                severity="major",
                fallback_used="辞書適用失敗→パース再試行またはフォールバック空リスト",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            result["phases"]["phase_1"] = {
                "status": "failed",
                "error": str(e)
            }
            # フォールバックとしてパースだけでも再試行、それもダメなら空
            try:
                corrected_segments = self._parse_srt(srt_path)
            except Exception as e_fallback:
                if isinstance(e_fallback, PROGRAM_ERRORS):
                    raise
                logger.warning("Phase 1 fallback SRT re-parse failed: %s", str(e_fallback))
                _log_quality_degradation(QualityDegradation(
                    phase="phase_1_fallback",
                    severity="major",
                    fallback_used="空リストで続行",
                    original_error=f"{type(e_fallback).__name__}: {str(e_fallback)[:200]}",
                ))
                corrected_segments = []
            return corrected_segments

    def _run_phase2_semantic_analysis(self, corrected_segments: List[Dict], result: Dict) -> tuple[Optional[SemanticSubtitleStore], Optional[Path]]:
        """Phase 2: Semantic分析"""
        logger.info("Phase 2: Semantic分析中...")
        store_path = self.output_dir / "semantic_store.json"
        try:
            if not corrected_segments:
                raise ValueError("Skipping Semantic store: no segments available.")

            semantic_store = create_semantic_store(corrected_segments, store_path)

            result["phases"]["phase_2"] = {
                "status": "completed",
                "topics": len(semantic_store.topics),
                "key_moments": len(semantic_store.key_moments)
            }
            logger.info(f"  トピック: {len(semantic_store.topics)}件")
            return semantic_store, store_path
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Phase 2 failed: {e}", exc_info=True)
            _log_quality_degradation(QualityDegradation(
                phase="phase_2",
                severity="moderate",
                fallback_used="Semantic分析=Noneで続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            result["phases"]["phase_2"] = {
                "status": "failed",
                "error": str(e)
            }
            return None, store_path

    def _run_phase3_telop_proposal(self, corrected_segments: List[Dict], result: Dict) -> tuple[List[Dict], List[Dict]]:
        """Phase 3: テロップ提案生成"""
        logger.info("Phase 3: テロップ提案生成中...")
        try:
            if not corrected_segments:
                raise ValueError("Skipping telop proposal: no segments available.")

            telop_candidates = extract_telops(corrected_segments, max_candidates=10)
            scene_proposals = propose_scenes(corrected_segments)

            result["phases"]["phase_3"] = {
                "status": "completed",
                "telop_candidates": len(telop_candidates),
                "scene_proposals": len(scene_proposals)
            }
            logger.info(f"  テロップ候補: {len(telop_candidates)}件")
            logger.info(f"  シーン提案: {len(scene_proposals)}件")
            return telop_candidates, scene_proposals
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Phase 3 failed: {e}", exc_info=True)
            _log_quality_degradation(QualityDegradation(
                phase="phase_3",
                severity="minor",
                fallback_used="テロップ提案=空リストで続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            result["phases"]["phase_3"] = {
                "status": "failed",
                "error": str(e)
            }
            return [], []

    def _run_phase4_asset_reference(self, result: Dict) -> Dict:
        """Phase 4: アセット参照確認"""
        logger.info("Phase 4: アセット参照確認中...")
        try:
            asset_report = get_assets_for("thumbnail")

            result["phases"]["phase_4"] = {
                "status": "completed",
                "available_assets": len(asset_report.get("available", [])),
                "missing_assets": len(asset_report.get("missing", []))
            }
            return asset_report
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Phase 4 failed: {e}", exc_info=True)
            _log_quality_degradation(QualityDegradation(
                phase="phase_4",
                severity="minor",
                fallback_used="アセット参照=空辞書で続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            result["phases"]["phase_4"] = {
                "status": "failed",
                "error": str(e)
            }
            return {"available": [], "missing": []}

    def _export_outputs(
        self,
        srt_path: Path,
        corrected_segments: List[Dict],
        telop_candidates: List[Dict],
        scene_proposals: List[Dict],
        result: Dict
    ) -> tuple[Optional[Path], Optional[Path]]:
        """SRT出力と提案レポート出力の書き込み"""
        # SRT出力
        srt_output = self.output_dir / "subtitles" / f"{srt_path.stem}_processed.srt"
        try:
            def _export_srt():
                srt_output.parent.mkdir(parents=True, exist_ok=True)
                # アトミック書き込み
                temp_srt = srt_output.with_suffix(".tmp_srt")
                SRTExporter.export(corrected_segments, temp_srt)
                if temp_srt.exists():
                    if srt_output.exists():
                        srt_output.unlink()
                    temp_srt.rename(srt_output)

            if corrected_segments:
                pipeline_retry(_export_srt, max_retries=3, backoff_base=1.0)
            else:
                raise ValueError("No segments to export to SRT.")

            result["phases"]["srt_export"] = {"status": "completed"}
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"SRT export failed: {e}", exc_info=True)
            _log_quality_degradation(QualityDegradation(
                phase="srt_export",
                severity="major",
                fallback_used="SRT出力=Noneで続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            result["phases"]["srt_export"] = {
                "status": "failed",
                "error": str(e)
            }
            srt_output = None

        # 提案レポート出力
        proposal_path = self.output_dir / "proposals" / f"{srt_path.stem}_proposals.json"
        try:
            def _export_proposals():
                proposal_path.parent.mkdir(parents=True, exist_ok=True)
                # アトミック書き込み
                temp_proposal = proposal_path.with_suffix(".tmp_json")
                with open(temp_proposal, "w", encoding="utf-8") as f:
                    json.dump({
                        "telop_candidates": telop_candidates,
                        "scene_proposals": scene_proposals
                    }, f, ensure_ascii=False, indent=2)

                if temp_proposal.exists():
                    if proposal_path.exists():
                        proposal_path.unlink()
                    temp_proposal.rename(proposal_path)

            pipeline_retry(_export_proposals, max_retries=3, backoff_base=1.0)

            result["phases"]["proposals_export"] = {"status": "completed"}
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Proposals export failed: {e}", exc_info=True)
            _log_quality_degradation(QualityDegradation(
                phase="proposals_export",
                severity="major",
                fallback_used="JSON出力=Noneで続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            result["phases"]["proposals_export"] = {
                "status": "failed",
                "error": str(e)
            }
            proposal_path = None

        return srt_output, proposal_path

    def _run_nhk_quality_scoring(self, srt_output: Optional[Path], result: Dict):
        """品質フィードバックフック: NHKスコアラ自動実行"""
        try:
            srt_out_str = str(srt_output) if srt_output else None
            if srt_out_str and Path(srt_out_str).exists():
                from services.nhk_quality_scorer import NHKQualityScorer
                scorer = NHKQualityScorer()
                # SRTベースのスコアリング（動画パスがない場合はSRTのみで採点）
                video_path = None  # 将来的に動画パスも渡せるよう設計
                score_report = scorer.score(
                    video_path=video_path or "",
                    srt_path=srt_out_str
                )
                result["quality_score"] = score_report.to_dict()
                logger.info(
                    f"NHK品質スコア: {score_report.overall_score}/100 "
                    f"({score_report.overall_grade})"
                )

                # 閾値以下の軸があればbug_hunterタスクを自動生成
                try:
                    from agents.orchestration import OrchestrationHub
                    hub = OrchestrationHub()
                    trigger_result = hub.trigger_quality_fix(
                        score_report.to_dict()
                    )
                    if trigger_result:
                        logger.info(f"品質フィードバック: {trigger_result}")
                        result["quality_feedback"] = trigger_result
                except Exception as e_trigger:
                    if isinstance(e_trigger, PROGRAM_ERRORS):
                        raise
                    logger.warning(
                        "Quality feedback trigger skipped: %s",
                        str(e_trigger)[:100]
                    )
            else:
                logger.info("品質スコアリングスキップ: SRT出力なし")
        except ImportError as e_import:
            logger.warning(
                "NHK quality scoring skipped (Scorer module missing): %s",
                str(e_import)[:100]
            )
        except Exception as e_quality:
            if isinstance(e_quality, PROGRAM_ERRORS):
                raise
            logger.warning(
                "NHK quality scoring skipped due to error: %s", str(e_quality), exc_info=True
            )

    def _parse_srt(self, srt_path: Path) -> List[Dict]:
        """SRTファイルをパース"""
        import re

        srt_path = Path(srt_path)

        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file does not exist: {srt_path}")

        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"Failed to read SRT file {srt_path}: {e}")
            raise

        segments = []
        blocks = content.strip().split("\n\n")

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) >= 3:
                try:
                    index = int(lines[0])
                    timestamp = lines[1]
                    text = "\n".join(lines[2:])

                    match = re.match(
                        r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})",
                        timestamp
                    )
                    if match:
                        h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
                        start = int(h1)*3600 + int(m1)*60 + int(s1) + int(ms1)/1000
                        end = int(h2)*3600 + int(m2)*60 + int(s2) + int(ms2)/1000

                        segments.append({
                            "id": f"seg_{index:03d}",
                            "start": start,
                            "end": end,
                            "text": text
                        })
                    else:
                        logger.warning(
                            "SRT block timestamp format mismatch: %s", timestamp[:100]
                        )
                except (IndexError, ValueError) as e:
                    logger.warning(
                        "SRT block parse skipped (index parse/regex failed): %s",
                        str(e)[:100]
                    )

        return segments

    def get_pipeline_status(self) -> Dict:
        """パイプラインステータスを取得"""
        status = {}
        try:
            status["proper_noun_entries"] = len(proper_noun_dict.get_all_entries())
            status["pending_confirmations"] = len(proper_noun_dict.get_pending())
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Error reading proper noun dict: {e}")
            _log_quality_degradation(QualityDegradation(
                phase="status_proper_noun_dict",
                severity="minor",
                fallback_used="辞書ステータス=0で続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            status["proper_noun_entries"] = 0
            status["pending_confirmations"] = 0

        try:
            status["available_assets"] = len(asset_library.assets)
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Error reading asset library: {e}")
            _log_quality_degradation(QualityDegradation(
                phase="status_asset_library",
                severity="minor",
                fallback_used="アセットステータス=0で続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            status["available_assets"] = 0

        try:
            status["pending_proposals"] = len(learning_loop.get_pending_proposals())
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Error reading learning loop: {e}")
            _log_quality_degradation(QualityDegradation(
                phase="status_learning_loop",
                severity="minor",
                fallback_used="学習ループステータス=0で続行",
                original_error=f"{type(e).__name__}: {str(e)[:200]}",
            ))
            status["pending_proposals"] = 0

        return status

    def _normalize_subtitles_for_quality(self, segments: List[Dict]) -> List[Dict]:
        """NHK品質基準（表示速度、行数、1行文字数）を満たすように字幕を補正する"""
        try:
            if not isinstance(segments, list):
                logger.warning("segments is not a list. Skipping normalization.")
                return []
            if not segments:
                return []
                
            # 1. 表示時間の延長（表示速度の緩和）
            # 各セグメントの目標秒数は文字数 / 5.5 (GOOD基準) とする。
            for i, seg in enumerate(segments):
                if not isinstance(seg, dict):
                    logger.warning(f"Segment at index {i} is not a dict: {type(seg)}")
                    continue
                text = seg.get("text", "")
                if not isinstance(text, str):
                    continue
                clean_text = text.replace(" ", "").replace("\n", "")
                chars_count = len(clean_text)
                if chars_count == 0:
                    continue
                    
                if "start" not in seg or "end" not in seg or seg["start"] is None or seg["end"] is None:
                    continue
                    
                try:
                    seg_start = float(seg["start"])
                    seg_end = float(seg["end"])
                except (ValueError, TypeError):
                    continue
                    
                target_duration = math.ceil((chars_count / 4.2) * 1000) / 1000.0  # 4.2 CPS (EXCELLENT基準) かつミリ秒切り上げ
                current_duration = seg_end - seg_start
                
                if current_duration < target_duration:
                    # 延長可能な最大終了時間（次のセグメントの開始時間、または無限）
                    next_start = None
                    if i < len(segments) - 1:
                        next_seg = segments[i+1]
                        if isinstance(next_seg, dict) and "start" in next_seg and next_seg["start"] is not None:
                            try:
                                next_start = float(next_seg["start"])
                            except (ValueError, TypeError):
                                pass
                    
                    max_end = next_start - 0.05 if next_start is not None else seg_start + target_duration + 5.0
                    
                    # 前方に広げられる最大開始時間（前のセグメントの終了時間、または0.0）
                    prev_end = None
                    if i > 0:
                        prev_seg = segments[i-1]
                        if isinstance(prev_seg, dict) and "end" in prev_seg and prev_seg["end"] is not None:
                            try:
                                prev_end = float(prev_seg["end"])
                            except (ValueError, TypeError):
                                pass
                    
                    min_start = prev_end + 0.05 if prev_end is not None else 0.0
                    
                    # 終了時間の最大値は、次のセグメントとのギャップを維持するため max_end を超えてはならない。
                    # ただし、開始時間との逆転を防ぐため、最低でも seg_start + 0.05 は確保したい。
                    # もし max_end が seg_start + 0.05 未満の場合、無理に終了時間を延ばすと次のセグメントと重なるため、
                    # 終了時間は max_end に制限した上で、開始時間を前にずらせるか試みる。
                    
                    limit_end = max_end if next_start is not None else seg_start + target_duration + 5.0
                    
                    # 補正後の候補
                    extended_end = min(seg_start + target_duration, limit_end)
                    extended_end = max(extended_end, seg_start)  # ガード: 終了時間は開始時間より前にならない
                    
                    # もし終了時間を extended_end にした場合、必要なデュレーションを確保するために開始時間をどこまで前にずらせるか
                    # 開始時間の候補は、目標デュレーションを満たすために必要な時間と、min_start の大きい方
                    extended_start = max(min_start, extended_end - target_duration)
                    extended_start = min(extended_start, seg_start)  # 元の開始時間より遅らせない
                    
                    # ギャップおよび順序が正しく維持されているか検証
                    if extended_end - extended_start >= 0.05 and (next_start is None or extended_end <= next_start - 0.05):
                        # 安全な範囲に収まる場合のみ更新を適用する
                        seg["start"] = extended_start
                        seg["end"] = extended_end

            # 2. 1行あたりの文字数制限（15文字）
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                text = seg.get("text", "")
                if not isinstance(text, str):
                    continue
                if not text:
                    continue
                    
                clean_text = text.replace("\n", " ").strip()
                
                # 15文字以内で改行を入れるように再構成する
                lines = []
                current_line = ""
                for char in clean_text:
                    if len(current_line) >= 15:
                        lines.append(current_line)
                        current_line = char
                    else:
                        current_line += char
                if current_line:
                    lines.append(current_line)
                    
                seg["text"] = "\n".join(lines)
                
            return segments
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Error in _normalize_subtitles_for_quality: {e}", exc_info=True)
            # 補正で予期せぬエラーが起きても元のセグメントを返して処理を継続する
            return segments


# CLI
def main():
    import sys

    if len(sys.argv) < 2:
        print("使用方法: python -m backend.antigravity_pipeline <input_srt>")
        return

    srt_path = Path(sys.argv[1])
    if not srt_path.exists():
        print(f"ファイルが見つかりません: {srt_path}")
        return

    pipeline = AntigravityPipeline()
    result = pipeline.process_srt(srt_path)

    print("\n=== 処理結果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
