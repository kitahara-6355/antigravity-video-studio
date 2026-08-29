"""
ProductionContext - 制作コンテキスト（全ての処理の中心オブジェクト）

PROJECT_CONSTITUTION §16 準拠:
- プラグイン間でのデータ共有
- 拡張可能なエクステンションシステム
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class ProductionPhase(Enum):
    """制作フェーズ"""
    INITIALIZATION = "initialization"
    PRE_PROCESS = "pre_process"
    ANALYSIS = "analysis"
    GENERATION = "generation"
    POST_PROCESS = "post_process"
    FINALIZATION = "finalization"


@dataclass
class ProductionContext:
    """
    制作コンテキスト
    
    全ての処理で共有される中心オブジェクト。
    プラグインはこのコンテキストを受け取り、処理結果を設定する。
    """
    # 基本情報
    task_id: str = ""
    video_paths: List[str] = field(default_factory=list)
    mood: str = "elegant"
    output_name: str = "output"
    
    # 処理状態
    phase: ProductionPhase = ProductionPhase.INITIALIZATION
    progress: float = 0.0
    current_step: str = "初期化中"
    
    # 出力パス
    output_dir: Path = field(default_factory=lambda: Path("output"))
    output_path: Optional[str] = None
    preview_url: Optional[str] = None
    
    # 解析結果
    subtitle_data: Optional[List[Dict]] = None
    scene_data: Optional[List[Dict]] = None
    semantic_chunks: Optional[List[Dict]] = None
    hook_analysis: Optional[Dict] = None
    
    # 生成物
    thumbnail_candidates: List[str] = field(default_factory=list)
    opening: Optional[str] = None
    ending: Optional[str] = None
    
    # ムード設定（design_tokensから取得）
    mood_settings: Dict[str, Any] = field(default_factory=dict)
    
    # 品質チェック結果
    #
    # **`quality_score` の 0.0 は「未計測」ではない**（R1.5-C4・9周目の指摘）。
    # 既定値が 0.0 なので、品質ゲートが一度も走らなくても「0.0点」が
    # そのまま `_build_result` を通って `GET /api/pipeline/report` の
    # 「総合スコア: 0.0点」や UI の「0点・❌不合格」になっていた。
    # **条件文が名指しする「常に 0.0 になる quality_score」そのもの。**
    #
    # 0.0 は実際に取りうる点なので、値の側で「無い」を表そうとすると必ず
    # 取り違える（8周目に入れた `None` 判定は、生産側が 0.0 を出すので
    # **本番から到達できなかった**）。**「測ったかどうか」を別に持つ。**
    # 立てるのは `QualityGateWorker` だけ。
    quality_score: float = 0.0
    quality_scored: bool = False
    quality_report: Optional[Dict] = None
    
    # 拡張データ（プラグイン固有データ）
    _extensions: Dict[str, Any] = field(default_factory=dict)
    
    # === 拡張データアクセス ===
    
    def get_extension(self, key: str, default: Any = None) -> Any:
        """拡張データを取得"""
        return self._extensions.get(key, default)
    
    def set_extension(self, key: str, value: Any) -> None:
        """拡張データを設定"""
        self._extensions[key] = value
    
    def has_extension(self, key: str) -> bool:
        """拡張データが存在するか確認"""
        return key in self._extensions
    
    # === 状態更新 ===
    
    def update_progress(self, progress: float, step: str = None) -> None:
        """進捗を更新"""
        try:
            val = float(progress)
            if val < 0.0:
                val = 0.0
            elif val > 1.0:
                val = 1.0
            self.progress = val
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid progress value '{progress}': {e}")
            
        if step is not None:
            self.current_step = str(step)
    
    def advance_phase(self, next_phase: Any) -> None:
        """フェーズを進める"""
        prev_phase = self.phase
        if isinstance(next_phase, ProductionPhase):
            self.phase = next_phase
        elif isinstance(next_phase, str):
            try:
                self.phase = ProductionPhase(next_phase)
            except ValueError:
                logger.error(f"Cannot advance phase to invalid string value: {next_phase}")
                return
        else:
            logger.error(f"Cannot advance phase to invalid type: {type(next_phase)}")
            return
            
        logger.info(f"Phase transition: {prev_phase.value} -> {self.phase.value}")
    
    # === シリアライズ ===
    
    def to_dict(self) -> Dict[str, Any]:
        """辞書形式にシリアライズ"""
        return {
            "task_id": self.task_id,
            "video_paths": [str(p) for p in self.video_paths] if self.video_paths else [],
            "mood": self.mood,
            "output_name": self.output_name,
            "phase": self.phase.value,
            "progress": self.progress,
            "current_step": self.current_step,
            "output_path": self.output_path,
            "preview_url": self.preview_url,
            "quality_score": self.quality_score,
            "extensions": self._extensions,
            "output_dir": str(self.output_dir),
            "subtitle_data": self.subtitle_data,
            "scene_data": self.scene_data,
            "semantic_chunks": self.semantic_chunks,
            "hook_analysis": self.hook_analysis,
            "thumbnail_candidates": [str(t) for t in self.thumbnail_candidates] if self.thumbnail_candidates else [],
            "opening": self.opening,
            "ending": self.ending,
            "mood_settings": self.mood_settings,
            "quality_report": self.quality_report
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProductionContext":
        """辞書形式からデシリアライズ"""
        if not isinstance(data, dict):
            logger.warning("from_dict received non-dict data, returning empty context")
            return cls()

        video_paths_raw = data.get("video_paths", [])
        if not isinstance(video_paths_raw, list):
            video_paths_raw = [video_paths_raw] if video_paths_raw else []
        video_paths = [str(p) for p in video_paths_raw if p is not None]

        ctx = cls(
            task_id=data.get("task_id", ""),
            video_paths=video_paths,
            mood=data.get("mood", "elegant"),
            output_name=data.get("output_name", "output")
        )
        
        phase_val = data.get("phase", "initialization")
        try:
            ctx.phase = ProductionPhase(phase_val)
        except ValueError:
            logger.warning(f"Invalid phase value '{phase_val}', falling back to INITIALIZATION")
            ctx.phase = ProductionPhase.INITIALIZATION
            
        ctx.progress = data.get("progress", 0.0)
        ctx.current_step = data.get("current_step", "")
        ctx.output_path = data.get("output_path")
        ctx.preview_url = data.get("preview_url")
        ctx.quality_score = data.get("quality_score", 0.0)
        
        extensions_val = data.get("extensions")
        ctx._extensions = extensions_val if isinstance(extensions_val, dict) else {}
        
        output_dir_val = data.get("output_dir")
        if output_dir_val:
            try:
                ctx.output_dir = Path(output_dir_val)
            except (TypeError, ValueError) as e:
                logger.warning(f"Invalid output_dir '{output_dir_val}': {e}, using default Path('output')")
                ctx.output_dir = Path("output")
        else:
            ctx.output_dir = Path("output")
            
        ctx.subtitle_data = data.get("subtitle_data")
        ctx.scene_data = data.get("scene_data")
        ctx.semantic_chunks = data.get("semantic_chunks")
        ctx.hook_analysis = data.get("hook_analysis")
        
        thumbnail_raw = data.get("thumbnail_candidates", [])
        ctx.thumbnail_candidates = [str(t) for t in thumbnail_raw] if isinstance(thumbnail_raw, list) else []
        
        ctx.opening = data.get("opening")
        ctx.ending = data.get("ending")
        
        mood_settings_val = data.get("mood_settings")
        ctx.mood_settings = mood_settings_val if isinstance(mood_settings_val, dict) else {}
        
        ctx.quality_report = data.get("quality_report")
        
        return ctx
    
    # === デザイントークン連携 ===
    
    def load_design_tokens(self, tokens_path: str = None) -> None:
        """design_tokens.jsonからムード設定を読み込み"""
        if tokens_path is None:
            resolved_path = Path(__file__).parent.parent / "branding" / "constitution.json"
        else:
            resolved_path = Path(tokens_path)
        
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                constitution = json.load(f)
            
            if not isinstance(constitution, dict):
                logger.warning(f"Constitution from {resolved_path} is not a dict")
                self.mood_settings = {}
                return

            design_tokens = constitution.get("design_tokens", {})
            if not isinstance(design_tokens, dict):
                design_tokens = {}
            
            mood_val = design_tokens.get(self.mood, {})
            self.mood_settings = mood_val if isinstance(mood_val, dict) else {}
            logger.info(f"Loaded design tokens for mood: {self.mood}")
        except (OSError, json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.warning(f"Failed to load design tokens from {resolved_path}: {e}")
            self.mood_settings = {}
