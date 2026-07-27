"""
字幕付きプレビュー生成システム
Phase 20: インタラクティブプレビューシステム

技術憲法9条（視覚確認プロトコル）準拠
"""

import subprocess
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ScenePreview:
    """シーンプレビュー情報"""
    scene_name: str
    video_path: str
    subtitle_path: Optional[str]
    screenshots: List[Dict[str, str]]  # {"timestamp": "00:01:00", "path": "...", "with_subtitle": True}
    telop_suggestions: List[Dict[str, Any]] = None
    errors: List[str] = None


@dataclass
class PreviewReport:
    """プレビューレポート"""
    title: str
    scenes: List[ScenePreview]
    proper_noun_warnings: List[Dict[str, str]] = None
    telop_config: Dict[str, Any] = None


class SubtitlePreviewGenerator:
    """
    字幕付きスクリーンショット生成
    
    機能:
    - 字幕付き/なしのスクリーンショット生成
    - 複数タイムスタンプ対応
    - walkthrough形式レポート出力
    """
    
    # 字幕スタイル（映画スタイル）
    SUBTITLE_STYLE = (
        "FontName=Noto Sans JP,"
        "FontSize=24,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=40"
    )
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def capture_with_subtitle(
        self,
        video_path: Path,
        subtitle_path: Path,
        timestamp: str,
        output_name: str
    ) -> Optional[Path]:
        """字幕付きスクリーンショットを生成
        
        重要: -ss を -i の後に置くことで、字幕フィルタが正しいタイムスタンプで動作する
        """
        output_path = self.output_dir / f"{output_name}_sub.jpg"
        
        # SRTパスをFFmpeg用にエスケープ
        srt_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
        
        subtitle_filter = f"subtitles='{srt_escaped}':force_style='{self.SUBTITLE_STYLE}'"
        
        # 重要: -ss を -i の後に置くことで字幕タイムスタンプが正しく同期される
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", timestamp,
            "-vf", subtitle_filter,
            "-vframes", "1",
            "-q:v", "2",
            str(output_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and output_path.exists():
                logger.info(f"Generated subtitle preview: {output_path}")
                return output_path
            else:
                logger.warning(f"FFmpeg failed: {result.stderr[:200]}")
                return None
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Error generating subtitle preview: {e}", exc_info=True)
            return None

    
    def capture_without_subtitle(
        self,
        video_path: Path,
        timestamp: str,
        output_name: str
    ) -> Optional[Path]:
        """字幕なしスクリーンショットを生成"""
        output_path = self.output_dir / f"{output_name}.jpg"
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", timestamp,
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and output_path.exists():
                return output_path
            return None
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Error generating preview: {e}", exc_info=True)
            return None
    
    def generate_scene_previews(
        self,
        scene_name: str,
        video_path: Path,
        subtitle_path: Optional[Path],
        timestamps: List[str]
    ) -> ScenePreview:
        """シーンのプレビューを生成"""
        screenshots = []
        
        for ts in timestamps:
            ts_safe = ts.replace(":", "-")
            output_name = f"{scene_name}_{ts_safe}"
            
            # 字幕付きスクショ
            has_sub = False
            if subtitle_path and subtitle_path.exists():
                sub_path = self.capture_with_subtitle(
                    video_path, subtitle_path, ts, output_name
                )
                if sub_path:
                    screenshots.append({
                        "timestamp": ts,
                        "path": str(sub_path),
                        "with_subtitle": True
                    })
                    has_sub = True
            
            # 字幕なしスクショ（フォールバック or 比較用）
            if not subtitle_path or not has_sub:
                plain_path = self.capture_without_subtitle(video_path, ts, output_name)
                if plain_path:
                    screenshots.append({
                        "timestamp": ts,
                        "path": str(plain_path),
                        "with_subtitle": False
                    })
        
        return ScenePreview(
            scene_name=scene_name,
            video_path=str(video_path),
            subtitle_path=str(subtitle_path) if subtitle_path else None,
            screenshots=screenshots
        )


class TelopPreviewGenerator:
    """
    テロップ付きスクリーンショット生成
    """
    
    def __init__(self, output_dir: Path, font_path: str = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Windows用フォントパス
        self.font_path = font_path or "C:/Windows/Fonts/YuGothB.ttc"
    
    def generate_telop_preview(
        self,
        video_path: Path,
        timestamp: str,
        telop_text: str,
        output_name: str,
        position: str = "top"  # "top" or "bottom"
    ) -> Optional[Path]:
        """テロップ付きスクリーンショットを生成"""
        output_path = self.output_dir / f"{output_name}_telop.jpg"
        
        # 位置設定
        y_pos = "50" if position == "top" else "h-th-50"
        
        # テロップテキストのエスケープ
        text_escaped = telop_text.replace("'", "\\'").replace(":", "\\:")
        font_escaped = self.font_path.replace("\\", "/").replace(":", "\\:")
        
        drawtext = (
            f"drawtext=text='{text_escaped}':"
            f"fontfile='{font_escaped}':"
            f"fontsize=28:fontcolor=white:"
            f"borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y={y_pos}"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", timestamp,
            "-i", str(video_path),
            "-vf", drawtext,
            "-vframes", "1",
            "-q:v", "2",
            str(output_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and output_path.exists():
                return output_path
            else:
                logger.warning(f"Telop generation failed: {result.stderr[:200]}")
                return None
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Error generating telop preview: {e}", exc_info=True)
            return None


class PreviewReportGenerator:
    """
    walkthrough.md形式のプレビューレポート生成
    """
    
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = Path(artifact_dir)
    
    def generate(self, report: PreviewReport) -> str:
        """walkthrough.md形式のレポートを生成"""
        md = f"# {report.title}\n\n"
        md += "> **技術憲法9条（視覚確認プロトコル）準拠**\n\n"
        md += "---\n\n"
        
        # 固有名詞警告
        if report.proper_noun_warnings:
            md += "## ⚠️ 誤字警告\n\n"
            md += "| 検出 | 正しい表記 | 箇所 |\n"
            md += "|:---|:---|:---|\n"
            for warn in report.proper_noun_warnings:
                md += f"| {warn['found']} | {warn['correct']} | {warn['location']} |\n"
            md += "\n---\n\n"
        
        # シーン別プレビュー
        for scene in report.scenes:
            md += f"## {scene.scene_name}\n\n"
            
            if scene.screenshots:
                md += "````carousel\n"
                for i, ss in enumerate(scene.screenshots):
                    if i > 0:
                        md += "<!-- slide -->\n"
                    
                    label = "字幕付き" if ss.get("with_subtitle") else "字幕なし"
                    path_str = ss['path']
                    try:
                        p = Path(path_str)
                        if p.is_absolute():
                            path_str = p.as_uri()
                        else:
                            path_str = p.resolve().as_uri()
                    except Exception:
                        pass
                    md += f"![{ss['timestamp']} {label}]({path_str})\n"
                md += "````\n\n"
            
            # テロップ提案
            if scene.telop_suggestions:
                md += "### テロップ候補\n\n"
                md += "| # | タイムスタンプ | テロップ案 | 理由 |\n"
                md += "|:---|:---|:---|:---|\n"
                for i, telop in enumerate(scene.telop_suggestions, 1):
                    md += f"| {i} | {telop['timestamp']} | {telop['text']} | {telop.get('reason', '')} |\n"
                md += "\n"
            
            md += "---\n\n"
        
        # 確認事項
        md += "## 確認事項\n\n"
        md += "**ドラフト動画を生成しますか？**\n"
        
        return md
    
    def save(self, report: PreviewReport, filename: str = "walkthrough.md") -> Path:
        """レポートをファイルに保存"""
        content = self.generate(report)
        output_path = self.artifact_dir / filename
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return output_path


# シングルトンインスタンス用ファクトリ
def create_preview_system(artifact_dir: Path):
    """プレビューシステムを初期化"""
    previews_dir = artifact_dir / "previews"
    
    return {
        "subtitle_generator": SubtitlePreviewGenerator(previews_dir),
        "telop_generator": TelopPreviewGenerator(previews_dir),
        "report_generator": PreviewReportGenerator(artifact_dir)
    }
