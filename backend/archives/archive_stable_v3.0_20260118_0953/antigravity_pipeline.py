"""
Antigravity 3.0 統合パイプライン
全Phaseを連携させた統合処理

使用方法:
    python -m backend.antigravity_pipeline <input_srt>
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Phase 1: Foundation
from proper_noun_dict import apply_dictionary, proper_noun_dict
from subtitle_normalizer import SRTExporter

# Phase 2: Context Intelligence
from semantic_store import SemanticSubtitleStoreV2 as SemanticSubtitleStore, create_semantic_store

# Phase 3: Generative Proposal
from telop_proposal_engine import telop_engine, extract_telops, propose_scenes

# Phase 4: Creative Asset Library
from asset_library import asset_library, scan_assets, get_assets_for

# Phase 6: Self-Review Engine
from self_review_engine import self_review_engine, review_and_improve

# Phase 7: Learning Loop
from learning_loop import learning_loop, record_approval, record_rejection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
        
        result = {
            "input": str(srt_path),
            "processed_at": datetime.now().isoformat(),
            "phases": {}
        }
        
        # Phase 1: 固有名詞辞書適用
        logger.info("Phase 1: 固有名詞辞書を適用中...")
        segments = self._parse_srt(srt_path)
        corrected_segments = []
        total_corrections = 0
        
        for seg in segments:
            corrected_text, corrections = apply_dictionary(seg["text"])
            seg["text"] = corrected_text
            seg["corrections"] = corrections
            corrected_segments.append(seg)
            total_corrections += len(corrections)
        
        result["phases"]["phase_1"] = {
            "status": "completed",
            "segments": len(corrected_segments),
            "corrections": total_corrections
        }
        logger.info(f"  修正数: {total_corrections}件")
        
        # Phase 2: Semantic分析
        logger.info("Phase 2: Semantic分析中...")
        store_path = self.output_dir / "semantic_store.json"
        semantic_store = create_semantic_store(corrected_segments, store_path)
        
        result["phases"]["phase_2"] = {
            "status": "completed",
            "topics": len(semantic_store.topics),
            "key_moments": len(semantic_store.key_moments)
        }
        logger.info(f"  トピック: {len(semantic_store.topics)}件")
        
        # Phase 3: テロップ提案
        logger.info("Phase 3: テロップ提案生成中...")
        telop_candidates = extract_telops(corrected_segments, max_candidates=10)
        scene_proposals = propose_scenes(corrected_segments)
        
        result["phases"]["phase_3"] = {
            "status": "completed",
            "telop_candidates": len(telop_candidates),
            "scene_proposals": len(scene_proposals)
        }
        logger.info(f"  テロップ候補: {len(telop_candidates)}件")
        logger.info(f"  シーン提案: {len(scene_proposals)}件")
        
        # Phase 4: アセット参照
        logger.info("Phase 4: アセット参照確認中...")
        asset_report = get_assets_for("thumbnail")
        
        result["phases"]["phase_4"] = {
            "status": "completed",
            "available_assets": len(asset_report.get("available", [])),
            "missing_assets": len(asset_report.get("missing", []))
        }
        
        # 出力
        logger.info("Phase 5-7: 出力生成中...")
        
        # SRT出力
        srt_output = self.output_dir / "subtitles" / f"{srt_path.stem}_processed.srt"
        srt_output.parent.mkdir(parents=True, exist_ok=True)
        SRTExporter.export(corrected_segments, srt_output)
        
        # 提案レポート出力
        proposal_path = self.output_dir / "proposals" / f"{srt_path.stem}_proposals.json"
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(proposal_path, "w", encoding="utf-8") as f:
            json.dump({
                "telop_candidates": telop_candidates,
                "scene_proposals": scene_proposals
            }, f, ensure_ascii=False, indent=2)
        
        result["outputs"] = {
            "srt": str(srt_output),
            "proposals": str(proposal_path),
            "semantic_store": str(store_path)
        }
        
        logger.info("=== 処理完了 ===")
        logger.info(f"SRT出力: {srt_output}")
        logger.info(f"提案レポート: {proposal_path}")
        
        return result
    
    def _parse_srt(self, srt_path: Path) -> List[Dict]:
        """SRTファイルをパース"""
        import re
        
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
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
                except:
                    pass
        
        return segments
    
    def get_pipeline_status(self) -> Dict:
        """パイプラインステータスを取得"""
        return {
            "proper_noun_entries": len(proper_noun_dict.get_all_entries()),
            "pending_confirmations": len(proper_noun_dict.get_pending()),
            "available_assets": len(asset_library.assets),
            "pending_proposals": len(learning_loop.get_pending_proposals())
        }


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
