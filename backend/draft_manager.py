"""
Draft Manager - ドラフト動画管理システム

Progressive Quality Pipeline Phase 1
低容量ドラフト動画の生成・管理・最終出力

設計原則:
- RAW動画は絶対に削除しない
- ドラフトは再生成可能なので一時ファイル扱い
- 段階的に品質を上げていく
"""

import subprocess
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DraftSettings:
    """ドラフト品質設定"""
    name: str
    resolution: str
    crf: int
    bitrate: str
    audio_bitrate: str = "128k"


# 品質プリセット
DRAFT_PRESETS = {
    "low": DraftSettings("低画質", "480", 32, "500k", "96k"),
    "medium": DraftSettings("中画質", "720", 28, "1M", "128k"),
    "high": DraftSettings("高画質", "1080", 23, "3M", "192k"),
    "final": DraftSettings("最終出力", "1080", 18, "8M", "320k")
}


def _parse_bitrate_to_kbps(bitrate_str: str) -> int:
    """ビットレート文字列（例: '500k', '1M'）を kbps 単位の数値に変換"""
    bitrate_str = bitrate_str.lower().strip()
    if bitrate_str.endswith('k'):
        return int(bitrate_str[:-1])
    elif bitrate_str.endswith('m'):
        return int(bitrate_str[:-1]) * 1024
    else:
        return int(bitrate_str)


class DraftManager:
    """ドラフト動画管理クラス"""
    
    def __init__(self, output_dir: str = None):
        """
        Args:
            output_dir: 出力ディレクトリ（未指定で自動設定）
        """
        if output_dir is None:
            base_dir = Path(__file__).parent
            output_dir = base_dir / "temp" / "drafts"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # カテゴリ別ディレクトリ
        self.dirs = {
            "drafts": self.output_dir / "drafts",
            "prefinal": self.output_dir / "prefinal",
            "final": self.output_dir / "final"
        }
        for d in self.dirs.values():
            d.mkdir(parents=True, exist_ok=True)
    
    def create_draft(
        self, 
        input_path: str, 
        quality: str = "medium",
        output_name: str = None
    ) -> Optional[str]:
        """
        低容量ドラフト動画を生成
        
        Args:
            input_path: 入力動画パス（RAWまたは処理済み）
            quality: 品質プリセット（low/medium/high）
            output_name: 出力ファイル名（未指定で自動生成）
        
        Returns:
            生成されたドラフトのパス、失敗時はNone
        """
        input_path = Path(input_path)
        if not input_path.exists():
            logger.error(f"Input file not found: {input_path}")
            return None
        
        settings = DRAFT_PRESETS.get(quality, DRAFT_PRESETS["medium"])
        
        if output_name is None:
            timestamp = int(time.time())
            output_name = f"draft_{input_path.stem}_{quality}_{timestamp}"
        
        output_path = self.dirs["drafts"] / f"{output_name}.mp4"
        
        # FFmpegコマンド構築
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-vf", f"scale=-2:{settings.resolution}",
            "-c:v", "libx264", "-preset", "fast", "-crf", str(settings.crf),
            "-b:v", settings.bitrate, "-maxrate", settings.bitrate, "-bufsize", f"{_parse_bitrate_to_kbps(settings.bitrate)*2}k",
            "-c:a", "aac", "-b:a", settings.audio_bitrate,
            "-movflags", "+faststart",
            str(output_path)
        ]
        
        logger.info(f"Creating draft: {input_path.name} -> {output_path.name} ({quality})")
        
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, 
                timeout=600, encoding='utf-8', errors='ignore'
            )
            
            if result.returncode == 0 and output_path.exists():
                # サイズ比較
                original_size = input_path.stat().st_size / (1024 * 1024)
                draft_size = output_path.stat().st_size / (1024 * 1024)
                reduction = (1 - draft_size / original_size) * 100 if original_size > 0 else 0
                
                logger.info(f"✅ Draft created: {draft_size:.1f}MB ({reduction:.1f}% reduction)")
                return str(output_path)
            else:
                logger.error(f"❌ Draft creation failed: {result.stderr[-500:]}")
                return None
                
        except subprocess.TimeoutExpired as e:
            logger.error(f"❌ Draft creation timed out (limit {e.timeout}s)")
            return None
        except OSError as e:
            logger.error(f"❌ Draft creation OS error (e.g. ffmpeg not found or permission issue): {e}")
            return None
        except subprocess.SubprocessError as e:
            logger.error(f"❌ Draft creation subprocess execution failed: {e}")
            return None
    
    def create_prefinal(
        self, 
        draft_paths: List[str],
        output_name: str = None
    ) -> Optional[str]:
        """
        複数のドラフトを結合して投稿前確認動画を生成
        
        Args:
            draft_paths: ドラフト動画パスのリスト
            output_name: 出力ファイル名
        
        Returns:
            生成された確認動画のパス
        """
        valid_paths = [p for p in draft_paths if Path(p).exists()]
        
        if len(valid_paths) == 0:
            logger.error("No valid draft files to merge")
            return None
        
        if len(valid_paths) == 1:
            # 1つだけならコピー
            import shutil
            if output_name is None:
                output_name = f"prefinal_{int(time.time())}"
            output_path = self.dirs["prefinal"] / f"{output_name}.mp4"
            shutil.copy(valid_paths[0], output_path)
            return str(output_path)
        
        # 複数ファイルの結合
        if output_name is None:
            output_name = f"prefinal_{int(time.time())}"
        output_path = self.dirs["prefinal"] / f"{output_name}.mp4"
        
        # concat list作成
        import uuid
        concat_list = self.output_dir / f"concat_list_{uuid.uuid4().hex}.txt"
        with open(concat_list, 'w', encoding='utf-8') as f:
            for path in valid_paths:
                escaped_path = path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
        
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(output_path)
        ]
        
        try:
            logger.info(f"Creating prefinal: {len(valid_paths)} drafts -> {output_path.name}")
            
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=300, encoding='utf-8', errors='ignore'
                )
                
                if result.returncode == 0 and output_path.exists():
                    size = output_path.stat().st_size / (1024 * 1024)
                    logger.info(f"✅ Prefinal created: {size:.1f}MB")
                    return str(output_path)
                else:
                    logger.error(f"❌ Prefinal creation failed: {result.stderr[-500:]}")
                    return None
                    
            except subprocess.TimeoutExpired as e:
                logger.error(f"❌ Prefinal creation timed out (limit {e.timeout}s)")
                return None
            except OSError as e:
                logger.error(f"❌ Prefinal creation OS error: {e}")
                return None
            except subprocess.SubprocessError as e:
                logger.error(f"❌ Prefinal creation subprocess failed: {e}")
                return None
        finally:
            concat_list.unlink(missing_ok=True)
    
    def create_final(
        self, 
        prefinal_path: str,
        output_name: str = None,
        srt_path: str = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        最終出力（高画質MP4 + SRT）を生成
        
        Args:
            prefinal_path: 投稿前確認動画のパス
            output_name: 出力ファイル名
            srt_path: 字幕SRTファイルパス（埋め込む場合）
        
        Returns:
            (最終MP4パス, SRTパス) のタプル
        """
        prefinal_path = Path(prefinal_path)
        if not prefinal_path.exists():
            logger.error(f"Prefinal file not found: {prefinal_path}")
            return None, None
        
        settings = DRAFT_PRESETS["final"]
        
        if output_name is None:
            output_name = f"final_{int(time.time())}"
        
        output_mp4 = self.dirs["final"] / f"{output_name}.mp4"
        output_srt = self.dirs["final"] / f"{output_name}.srt"
        
        # 高画質エンコード
        cmd = [
            "ffmpeg", "-y", "-i", str(prefinal_path),
            "-vf", f"scale=-2:{settings.resolution}",
            "-c:v", "libx264", "-preset", "slow", "-crf", str(settings.crf),
            "-b:v", settings.bitrate, "-maxrate", settings.bitrate,
            "-c:a", "aac", "-b:a", settings.audio_bitrate,
            "-movflags", "+faststart",
            str(output_mp4)
        ]
        
        logger.info(f"Creating final output: {prefinal_path.name} -> {output_mp4.name}")
        
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=1800, encoding='utf-8', errors='ignore'
            )
            
            if result.returncode == 0 and output_mp4.exists():
                size = output_mp4.stat().st_size / (1024 * 1024)
                logger.info(f"✅ Final output created: {size:.1f}MB")
                
                # SRTコピー（指定されている場合）
                if srt_path and Path(srt_path).exists():
                    import shutil
                    shutil.copy(srt_path, output_srt)
                    logger.info(f"✅ SRT copied: {output_srt.name}")
                    return str(output_mp4), str(output_srt)
                
                return str(output_mp4), None
            else:
                logger.error(f"❌ Final output failed: {result.stderr[-500:]}")
                return None, None
                
        except subprocess.TimeoutExpired as e:
            logger.error(f"❌ Final output timed out (limit {e.timeout}s)")
            return None, None
        except OSError as e:
            logger.error(f"❌ Final output OS error: {e}")
            return None, None
        except subprocess.SubprocessError as e:
            logger.error(f"❌ Final output subprocess failed: {e}")
            return None, None
    
    def get_stats(self) -> Dict:
        """ストレージ使用状況を取得"""
        stats = {}
        
        for category, dir_path in self.dirs.items():
            files = list(dir_path.glob("*.mp4"))
            total_size = sum(f.stat().st_size for f in files) / (1024 * 1024)
            stats[category] = {
                "count": len(files),
                "size_mb": round(total_size, 2),
                "files": [f.name for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[:5]]
            }
        
        return stats


# シングルトンインスタンス
draft_manager = DraftManager()
