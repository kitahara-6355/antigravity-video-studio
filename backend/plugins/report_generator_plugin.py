"""
Report Generator Plugin - 生成物レポートプラグイン

PROJECT_CONSTITUTION §16 準拠:
- カルーセル形式
- 網羅的レポート
"""
from core import Plugin, PluginPhase, ProductionContext
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)


class ReportGeneratorPlugin(Plugin):
    """
    生成物レポートプラグイン
    
    制作完了後に全生成物をまとめたMarkdownレポートを作成する。
    カルーセル形式で視覚的に確認しやすくする。
    """
    
    name = "report_generator"
    phase = PluginPhase.FINALIZATION
    priority = 100  # 最後に実行

    def _to_file_url(self, path_str: str) -> str:
        """パスを安全な file:/// URL に変換してエンコードする"""
        if not path_str or not isinstance(path_str, str):
            return ""
        if "://" in path_str:
            return path_str
        from urllib.parse import quote
        # Windowsのバックスラッシュは Posix スタイル / に統一してからエンコード
        try:
            p = Path(path_str).resolve()
            return "file:///" + quote(p.as_posix(), safe="/:")
        except Exception:
            return ""
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """生成物レポートを作成"""
        self.log("Generating production report")
        
        try:
            report = self._generate_report(context)
            
            # レポートを保存
            report_path = context.output_dir / "generation_report.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            
            context.set_extension("report_path", str(report_path))
            self.log(f"Report saved: {report_path}")
        except OSError as e:
            logger.error(f"Failed to write production report (I/O error): {e}", exc_info=True)
            context.set_extension("report_path", None)
        except Exception as e:
            # TD-1303: 堅牢性向上のための広範な例外捕捉（ACCEPTED_SAFETY）
            logger.error(f"Failed to generate production report: {e}", exc_info=True)
            context.set_extension("report_path", None)
            
        return context
    
    def _generate_report(self, context: ProductionContext) -> str:
        """レポートを生成"""
        lines = []
        
        # ヘッダー
        lines.append("# 🎬 生成物レポート\n")
        lines.append(f"> 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"> タスクID: `{context.task_id}`")
        lines.append(f"> ムード: **{context.mood}**\n")
        
        # サマリー
        lines.append("## 📊 サマリー\n")
        lines.append(f"| 項目 | 状態 |")
        lines.append("|:---|:---|")
        
        thumbnail_count = len(context.thumbnail_candidates) if isinstance(context.thumbnail_candidates, (list, tuple)) else 0
        lines.append(f"| サムネイル候補 | {thumbnail_count}枚 |")
        lines.append(f"| オープニング | {'✅' if context.opening else '❌'} |")
        lines.append(f"| エンディング | {'✅' if context.ending else '❌'} |")
        lines.append(f"| BGM | {'✅' if context.get_extension('music_layer') else '❌'} |")
        lines.append(f"| チャプター | {context.get_extension('chapters_count', 0)}件 |")
        
        # **未計測を「0.0/100」として出さない**（R1.5-C4・2026-08-27）。
        # この経路（`backend/core/context.py`）に品質ゲートは繋がっておらず、
        # dataclass の既定値 0.0 がそのまま「0.0/100」と表示されていた。
        # **測っていないことを、0点という測定結果に見せない。**
        quality_score = context.quality_score
        if not isinstance(quality_score, (int, float)) or not quality_score:
            lines.append("| 品質スコア | **未計測**（この経路に品質ゲートは"
                         "繋がっていません）|" + chr(10))
        else:
            lines.append(f"| 品質スコア | {quality_score:.1f}/100 |\n")
        
        # サムネイルカルーセル
        if isinstance(context.thumbnail_candidates, (list, tuple)) and context.thumbnail_candidates:
            lines.append("## 🖼️ サムネイル候補\n")
            lines.append("````carousel")
            for i, thumb in enumerate(context.thumbnail_candidates):
                lines.append(f"![案{i+1}]({self._to_file_url(thumb)})")
                if i < len(context.thumbnail_candidates) - 1:
                    lines.append("<!-- slide -->")
            lines.append("````\n")
        
        # OP/ED動画
        if context.opening or context.ending:
            lines.append("## 🎥 オープニング/エンディング\n")
            if context.opening:
                lines.append(f"### オープニング")
                lines.append(f"![オープニング]({self._to_file_url(context.opening)})\n")
            if context.ending:
                lines.append(f"### エンディング")
                lines.append(f"![エンディング]({self._to_file_url(context.ending)})\n")
        
        # BGM設定
        music = context.get_extension("music_layer")
        if music and isinstance(music, str):
            lines.append("## 🎵 BGM設定\n")
            lines.append(f"| 設定 | 値 |")
            lines.append("|:---|:---|")
            lines.append(f"| 曲 | `{Path(music).name}` |")
            lines.append(f"| スタイル | {context.get_extension('music_style', '-')} |")
            
            volume = context.get_extension("music_volume", 0.3)
            if not isinstance(volume, (int, float)):
                volume = 0.3
            lines.append(f"| 音量 | {volume * 100:.0f}% |")
            
            ducking = context.get_extension("music_ducking", {})
            if isinstance(ducking, dict) and ducking.get("enabled"):
                duck_level = ducking.get('duck_level', 0.15)
                if not isinstance(duck_level, (int, float)):
                    duck_level = 0.15
                lines.append(f"| ダッキング | 有効（{duck_level * 100:.0f}%） |\n")
        
        # チャプター
        chapters = context.get_extension("chapters", [])
        if chapters and isinstance(chapters, (list, tuple)):
            lines.append("## 📑 自動チャプター\n")
            youtube_chapters = context.get_extension("youtube_chapters", "")
            if not isinstance(youtube_chapters, str):
                youtube_chapters = ""
            lines.append("```")
            lines.append(youtube_chapters)
            lines.append("```\n")
        
        # デザイントークン
        if context.mood_settings:
            lines.append("## 🎨 適用デザイントークン\n")
            lines.append("```json")
            lines.append(json.dumps(context.mood_settings, ensure_ascii=False, indent=2))
            lines.append("```\n")
        
        # 品質レポート
        if context.quality_report and isinstance(context.quality_report, dict):
            lines.append("## ✅ 品質チェック結果\n")
            report = context.quality_report
            score = report.get('score', 0)
            if not isinstance(score, (int, float)):
                score = 0.0
            lines.append(f"- **スコア**: {score:.1f}/100")
            lines.append(f"- **レベル**: {report.get('level', '-')}")
            
            issues = report.get('issues', [])
            if isinstance(issues, (list, tuple)) and issues:
                lines.append(f"- **問題点**: {len(issues)}件")
        
        # フッター
        lines.append("---")
        lines.append("\n*Generated by Antigravity Video Studio v4.0*")
        
        return "\n".join(lines)
    
    def can_execute(self, context: ProductionContext) -> bool:
        """常に実行可能"""
        return True
