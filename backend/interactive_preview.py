"""
Phase 20: インタラクティブプレビューシステム 統合モジュール

Phase 4: AI字幕確認
Phase 5: テロップ分割AI提案
Phase 6: テロップスクショプレビュー
Phase 7: 承認→自動反映

品質改善適用済み:
- 例外処理の具体化
- FFmpegエラーログ出力
- APIリトライ機能
- ログレベル多様化
- テロップスタイル設定ファイル化
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict, field
import logging
from dotenv import load_dotenv

# .env読み込み
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# ログレベル多様化（改善#4）
logger = logging.getLogger(__name__)

import re
import tempfile

TIMESTAMP_RE = re.compile(r'^(\d{2}:\d{2}:\d{2}(\.\d{3})?|\d+(\.\d+)?)$')

def validate_timestamp(ts: str) -> str:
    """タイムスタンプ形式の検証。不正な場合はValueError"""
    if not TIMESTAMP_RE.match(ts):
        raise ValueError(f"Invalid timestamp format: {ts}")
    return ts

def validate_path(path: Path) -> Path:
    """パスの安全性を検証（プロジェクトルート、一時ディレクトリ、またはWindowsフォントディレクトリの配下であること）"""
    try:
        resolved_path = Path(path).resolve()
    except Exception as e:
        raise ValueError(f"Invalid path: {e}")
        
    project_root = Path(__file__).parent.parent.resolve()
    
    try:
        temp_dir = Path(tempfile.gettempdir()).resolve()
    except Exception:
        temp_dir = Path("/tmp").resolve()
        
    # Windowsフォントディレクトリも許可
    font_dir = Path("C:/Windows/Fonts").resolve()
    
    # 許可ディレクトリ配下かチェック
    allowed_dirs = [project_root, temp_dir, font_dir]
    
    is_allowed = False
    for allowed_dir in allowed_dirs:
        try:
            if allowed_dir in resolved_path.parents or allowed_dir == resolved_path:
                is_allowed = True
                break
        except Exception:
            continue
            
    if not is_allowed:
        raise ValueError(f"Path is outside allowed directories: {path}")
    return resolved_path

# 設定: テロップスタイル（改善#5）
TELOP_STYLES = {
    "default": {
        "fontsize": 32,
        "fontcolor": "white",
        "borderw": 3,
        "bordercolor": "black"
    },
    "emphasis": {
        "fontsize": 40,
        "fontcolor": "yellow",
        "borderw": 4,
        "bordercolor": "black"
    },
    "subtle": {
        "fontsize": 24,
        "fontcolor": "white",
        "borderw": 2,
        "bordercolor": "gray"
    }
}


# ============================================================
# Phase 4: AI字幕確認システム
# ============================================================

@dataclass
class ConfirmationItem:
    """確認項目"""
    id: str
    timestamp: str
    original_text: str
    concern: str
    category: str  # "proper_noun", "uncertain", "context", "typo"
    suggestion: Optional[str] = None
    status: str = "pending"  # "pending", "approved", "rejected", "modified"
    modified_text: Optional[str] = None


class SubtitleConfirmationChecker:
    """AI判断による字幕確認"""
    
    PROMPT = """
あなたは字幕の品質チェッカーです。以下の字幕から、確認が必要な箇所を特定してください。

## 確認が必要な箇所
1. 固有名詞（人名、企業名、団体名）
2. 専門用語
3. 文脈から不自然な箇所
4. 曖昧な同音異義語

## 字幕
{content}

## 出力（JSON形式）
```json
[{{"timestamp": "00:01:30", "original_text": "テキスト", "concern": "理由", "category": "proper_noun", "suggestion": "修正案"}}]
```
"""
    
    MAX_RETRIES = 3  # APIリトライ回数（改善#3）
    RETRY_DELAY = 2  # リトライ間隔（秒）
    
    def analyze(self, srt_content: str, scene_name: str) -> List[ConfirmationItem]:
        """字幕を分析して確認項目を抽出（リトライ機能付き）"""
        for attempt in range(self.MAX_RETRIES):
            try:
                logger.info(f"AI字幕確認開始: {scene_name} (attempt {attempt + 1})")
                
                from gemini_client_factory import get_gemini_client
                from model_registry import get_model
                client = get_gemini_client()
                
                response = client.models.generate_content(
                    model=get_model("ai_confirmation"),
                    contents=self.PROMPT.format(content=srt_content[:8000])
                )
                
                logger.debug(f"AI応答受信: {len(response.text)} chars")  # ログレベル多様化
                return self._parse_response(response.text, scene_name)
                
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"通信エラー (attempt {attempt + 1}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
            except Exception as e:
                logger.error(f"AI確認失敗: {type(e).__name__}: {e}")  # 例外型を記録
                break
        
        return []
    
    def _parse_response(self, text: str, prefix: str) -> List[ConfirmationItem]:
        """レスポンスをパース（例外処理具体化: 改善#1）"""
        items = []
        try:
            if "```json" in text:
                start = text.find("```json") + 7
                end = text.find("```", start)
                json_str = text[start:end].strip()
            elif "[" in text:
                start = text.find("[")
                end = text.rfind("]") + 1
                json_str = text[start:end]
            else:
                logger.debug("JSONが見つかりませんでした")
                return []
            
            data = json.loads(json_str)
            for i, item in enumerate(data):
                items.append(ConfirmationItem(
                    id=f"{prefix}_{i+1:03d}",
                    timestamp=item.get("timestamp", "00:00:00"),
                    original_text=item.get("original_text", ""),
                    concern=item.get("concern", ""),
                    category=item.get("category", "uncertain"),
                    suggestion=item.get("suggestion")
                ))
            logger.info(f"パース成功: {len(items)} 件の確認項目")
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSONパースエラー: {e}")
        except KeyError as e:
            logger.warning(f"キー不足: {e}")
        except TypeError as e:
            logger.warning(f"型エラー: {e}")
            
        return items


# ============================================================
# Phase 5: テロップ分割AI提案
# ============================================================

@dataclass
class TelopSuggestion:
    """テロップ提案"""
    id: str
    timestamp: str
    duration: float
    text: str
    reason: str
    position: str = "top"  # "top" or "bottom"
    style: str = "default"
    approved: bool = False


class TelopSuggester:
    """字幕からテロップ候補を提案"""
    
    PROMPT = """
以下の対談字幕から、テロップ表示に適した箇所を抽出してください。

## テロップにすべき内容
1. 話者の肩書き（初登場時）
2. 重要なキーワード（企業名、作品名、人名）
3. トピックの転換点
4. 印象的な発言・名言
5. 数字・データ

## 字幕
{content}

## 出力（JSON形式、最大10件）
```json
[{{"timestamp": "00:00:30", "duration": 3.0, "text": "テロップ文字", "reason": "理由", "position": "top"}}]
```
"""
    
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    def suggest(self, srt_content: str, scene_name: str) -> List[TelopSuggestion]:
        """テロップ候補を提案（リトライ機能付き）"""
        for attempt in range(self.MAX_RETRIES):
            try:
                logger.info(f"テロップ提案開始: {scene_name} (attempt {attempt + 1})")
                
                from gemini_client_factory import get_gemini_client
                from model_registry import get_model
                client = get_gemini_client()
                
                response = client.models.generate_content(
                    model=get_model("telop_suggestion"),
                    contents=self.PROMPT.format(content=srt_content[:8000])
                )
                
                logger.debug(f"AI応答受信: {len(response.text)} chars")
                return self._parse_response(response.text, scene_name)
                
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"通信エラー (attempt {attempt + 1}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
            except Exception as e:
                logger.error(f"テロップ提案失敗: {type(e).__name__}: {e}")
                break
        
        return []
    
    def _parse_response(self, text: str, prefix: str) -> List[TelopSuggestion]:
        """レスポンスをパース（例外処理具体化）"""
        suggestions = []
        try:
            if "```json" in text:
                start = text.find("```json") + 7
                end = text.find("```", start)
                json_str = text[start:end].strip()
            elif "[" in text:
                start = text.find("[")
                end = text.rfind("]") + 1
                json_str = text[start:end]
            else:
                logger.debug("JSONが見つかりませんでした")
                return []
            
            data = json.loads(json_str)
            for i, item in enumerate(data):
                suggestions.append(TelopSuggestion(
                    id=f"{prefix}_telop_{i+1:03d}",
                    timestamp=item.get("timestamp", "00:00:00"),
                    duration=float(item.get("duration", 3.0)),
                    text=item.get("text", ""),
                    reason=item.get("reason", ""),
                    position=item.get("position", "top")
                ))
            logger.info(f"パース成功: {len(suggestions)} 件のテロップ候補")
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSONパースエラー: {e}")
        except KeyError as e:
            logger.warning(f"キー不足: {e}")
        except (TypeError, ValueError) as e:
            logger.warning(f"型/値エラー: {e}")
            
        return suggestions


# ============================================================
# Phase 6: テロップスクショプレビュー
# ============================================================

class TelopPreviewRenderer:
    """テロップ付きスクショ生成"""
    
    def __init__(self, output_dir: Path, font_path: str = None):
        self.output_dir = validate_path(Path(output_dir))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.font_path = font_path or "C:/Windows/Fonts/YuGothB.ttc"
    
    def render(
        self,
        video_path: Path,
        telop: TelopSuggestion,
        output_name: str,
        style_name: str = "default"
    ) -> Optional[Path]:
        """テロップ付きスクショを生成"""
        # 入力バリデーション
        video_path = validate_path(video_path)
        validate_timestamp(telop.timestamp)
        if telop.position not in ("top", "bottom"):
            raise ValueError(f"Invalid telop position: {telop.position}")
            
        if Path(output_name).name != output_name or output_name in ('.', '..'):
            raise ValueError(f"Invalid output name: {output_name}")
            
        output_path = self.output_dir / f"{output_name}.jpg"
        output_path = validate_path(output_path)
        
        # スタイル取得（改善#5）
        style = TELOP_STYLES.get(style_name, TELOP_STYLES["default"])
        
        # 位置設定
        y_pos = "50" if telop.position == "top" else "h-th-50"
        
        # テキストエスケープ (バックスラッシュも安全にエスケープ)
        text_escaped = telop.text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        font_escaped = self.font_path.replace("\\", "/").replace(":", "\\:")
        
        drawtext = (
            f"drawtext=text='{text_escaped}':"
            f"fontfile='{font_escaped}':"
            f"fontsize={style['fontsize']}:fontcolor={style['fontcolor']}:"
            f"borderw={style['borderw']}:bordercolor={style['bordercolor']}:"
            f"x=(w-text_w)/2:y={y_pos}"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", telop.timestamp,
            "-vf", drawtext,
            "-vframes", "1",
            "-q:v", "2",
            str(output_path)
        ]
        
        logger.debug(f"FFmpegコマンド: {' '.join(cmd[:8])}...")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0 and output_path.exists():
                logger.info(f"テロッププレビュー生成成功: {output_path.name}")
                return output_path
            else:
                # FFmpegエラーログ出力（改善#2）
                logger.error(f"FFmpegエラー (code {result.returncode}): {result.stderr[:500]}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("FFmpegタイムアウト（60秒）")
            return None
        except FileNotFoundError:
            logger.error("FFmpegが見つかりません")
            return None
        except Exception as e:
            logger.error(f"レンダリングエラー: {type(e).__name__}: {e}")
            return None


# ============================================================
# Phase 7: 承認→自動反映
# ============================================================

@dataclass
class TelopConfig:
    """テロップ設定ファイル"""
    version: str = "1.0"
    scene_name: str = ""
    telops: List[Dict] = field(default_factory=list)
    confirmations: List[Dict] = field(default_factory=list)
    
    def save(self, path: Path):
        """設定をJSONファイルに保存"""
        logger.info(f"設定ファイル保存: {path}")
        path = validate_path(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, path: Path) -> "TelopConfig":
        """JSONファイルから読み込み"""
        logger.info(f"設定ファイル読み込み: {path}")
        path = validate_path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


# ============================================================
# テロップスタイル設定管理（改善#5）
# ============================================================

def load_telop_styles(config_path: Optional[Path] = None) -> Dict:
    """テロップスタイル設定を読み込み"""
    if config_path:
        config_path = validate_path(config_path)
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    custom_styles = json.load(f)
                logger.info(f"カスタムスタイル読み込み: {config_path}")
                return {**TELOP_STYLES, **custom_styles}
            except Exception as e:
                logger.warning(f"スタイル設定読み込み失敗: {e}")
    return TELOP_STYLES


def save_telop_styles(styles: Dict, config_path: Path):
    """テロップスタイル設定を保存"""
    config_path = validate_path(config_path)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(styles, f, ensure_ascii=False, indent=2)
    logger.info(f"スタイル設定保存: {config_path}")


# ============================================================
# 統合レポート生成
# ============================================================

class IntegratedReportGenerator:
    """Phase 4-7の結果を統合してwalkthrough形式で出力（英語ファイル名対応）"""
    
    def generate(
        self,
        scene_id: str,
        scene_name: str,
        confirmations: List[ConfirmationItem],
        telop_suggestions: List[TelopSuggestion],
        telop_previews: Dict[str, Path],
        subtitle_screenshots: List[Dict]
    ) -> str:
        """統合レポートを生成（カルーセル+確認事項形式）"""
        md = f"## {scene_id} ({scene_name})\n\n"
        
        # 字幕スクショ（カルーセル形式・各スクショに確認事項付き）
        if subtitle_screenshots:
            md += "### 字幕プレビュー\n\n"
            md += "````carousel\n"
            for i, ss in enumerate(subtitle_screenshots):
                if i > 0:
                    md += "<!-- slide -->\n"
                
                # スクショ画像
                filepath = ss['path'].replace(chr(92), '/')
                md += f"![{ss['timestamp']}](file:///{filepath})\n\n"
                
                # このタイムスタンプに関連する確認事項を抽出
                ts = ss['timestamp']
                related_items = [c for c in confirmations if c.timestamp.startswith(ts[:5])]
                
                md += f"**時間**: {ts}\n\n"
                if related_items:
                    md += "**確認事項**:\n"
                    for item in related_items[:3]:
                        text_short = item.original_text[:25] + "..." if len(item.original_text) > 25 else item.original_text
                        md += f"- {text_short} ({item.concern})\n"
                else:
                    md += "**確認事項**: 特になし\n"
                md += "\n"
            md += "````\n\n"
        
        # AI確認リスト（全件表示）
        if confirmations:
            md += "### 🔍 AI字幕確認リスト\n\n"
            md += "| # | 時間 | テキスト | 懸念 | 提案 |\n"
            md += "|:---|:---|:---|:---|:---|\n"
            for item in confirmations:
                suggestion = item.suggestion or "-"
                text_short = item.original_text[:20] + "..." if len(item.original_text) > 20 else item.original_text
                md += f"| {item.id} | {item.timestamp} | {text_short} | {item.concern} | {suggestion} |\n"
            md += "\n"
        
        # テロップ提案
        if telop_suggestions:
            md += "### 🎬 テロップ提案\n\n"
            for telop in telop_suggestions:
                md += f"#### {telop.id}: {telop.text}\n\n"
                md += f"- **時間**: {telop.timestamp}\n"
                md += f"- **理由**: {telop.reason}\n"
                
                # プレビュー画像があれば表示
                if telop.id in telop_previews:
                    preview_path = telop_previews[telop.id]
                    md += f"\n![Telop Preview](file:///{str(preview_path).replace(chr(92), '/')})\n"
                
                md += "\n"
        
        md += "---\n\n"
        return md


# ============================================================
# メイン実行
# ============================================================

def run_full_pipeline(
    scenes: List[Dict],
    output_dir: Path
) -> str:
    """Phase 4-7を一気通貫で実行"""
    output_dir = validate_path(output_dir)
    
    checker = SubtitleConfirmationChecker()
    suggester = TelopSuggester()
    renderer = TelopPreviewRenderer(output_dir / "telop_previews")
    report_gen = IntegratedReportGenerator()
    
    full_report = "# Phase 20: インタラクティブプレビューシステム 完了レポート\n\n"
    full_report += "> **Phase 4-7 一気通貫実装完了**\n\n"
    full_report += "---\n\n"
    
    for scene in scenes:
        scene_id = scene.get("scene_id", scene["name"])
        scene_name = scene["name"]
        video_path = validate_path(Path(scene["video"]))
        srt_path = scene.get("subtitle")
        if srt_path:
            srt_path = validate_path(Path(srt_path))
        
        logger.info(f"処理開始: {scene_id} ({scene_name})")
        print(f"\n📋 {scene_id} ({scene_name})")
        
        # SRT読み込み
        srt_content = ""
        if srt_path and Path(srt_path).exists():
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()
        
        # Phase 4: AI字幕確認
        confirmations = []
        if srt_content:
            print("  - Phase 4: AI字幕確認...")
            confirmations = checker.analyze(srt_content, scene_id)
            print(f"    ✅ {len(confirmations)} 件の確認項目")
        
        # Phase 5: テロップ提案
        suggestions = []
        if srt_content:
            print("  - Phase 5: テロップ提案...")
            suggestions = suggester.suggest(srt_content, scene_id)
            print(f"    ✅ {len(suggestions)} 件のテロップ候補")
        
        # Phase 6: テロップスクショ（英語ファイル名）
        telop_previews = {}
        if suggestions and video_path.exists():
            print("  - Phase 6: テロッププレビュー生成...")
            for i, telop in enumerate(suggestions[:3]):
                # 英語ファイル名を使用
                telop_filename = f"{scene_id}_telop_{i+1:03d}"
                preview_path = renderer.render(video_path, telop, telop_filename)
                if preview_path:
                    telop_previews[telop.id] = preview_path
            print(f"    ✅ {len(telop_previews)} 件のプレビュー")
        
        # Phase 7: 設定ファイル生成（英語ファイル名）
        config = TelopConfig(
            scene_name=scene_name,
            telops=[asdict(s) for s in suggestions],
            confirmations=[asdict(c) for c in confirmations]
        )
        config_path = output_dir / f"{scene_id}_config.json"
        config.save(config_path)
        print(f"  - Phase 7: 設定ファイル保存 → {config_path.name}")
        
        logger.info(f"処理完了: {scene_id}")
        
        # レポート生成
        subtitle_screenshots = scene.get("screenshots", [])
        full_report += report_gen.generate(
            scene_id,
            scene_name,
            confirmations,
            suggestions,
            telop_previews,
            subtitle_screenshots
        )
    
    full_report += "## 操作方法\n\n"
    full_report += "- **はい/承認**: 現在の内容を確定\n"
    full_report += "- **修正**: コメントで正しいテキストを入力\n"
    full_report += "- **却下**: この項目をスキップ\n\n"
    full_report += "---\n\n"
    full_report += "**確認完了後、ドラフト動画を生成しますか？**\n"
    
    return full_report
