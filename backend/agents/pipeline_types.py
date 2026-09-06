"""
Pipeline Types — パイプライン共有型定義

pipeline_coordinator.py (1,730行) から型定義を分離し、
パイプライン全体で共有するデータ構造を集約する。

Sprint B-1 で導入:
  - StageResult: ステージ実行結果
  - PipelineContext: パイプライン共有コンテキスト
  - PipelineStageWorker: Worker 基底クラス
  - Segment: 字幕セグメントの型安全 dataclass (新規)

設計思想:
  - 循環import回避のため、型定義を独立モジュールに分離
  - pipeline_coordinator.py で re-export し、既存の40+箇所のimportを変更不要に
  - Segment dataclass で dict ベースのセグメントを型安全に置き換え
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
from abc import ABC, abstractmethod


# ============================================================
# Segment dataclass (Sprint B-1 新規)
# ============================================================

@dataclass
class Segment:
    """字幕セグメントの型安全表現

    Whisper から出力される字幕セグメントを dict から dataclass に昇格。
    start/end: 表示用タイムスタンプ（テキスト整形で再計算される可能性あり）
    text: 字幕テキスト
    sourceStart/sourceEnd: Whisper原本タイムスタンプ（不変）

    既存の dict ベースのセグメントとの相互変換メソッド (from_dict / to_dict) を提供。
    """
    start: float
    end: float
    text: str = ""
    sourceStart: Optional[float] = None
    sourceEnd: Optional[float] = None

    def __post_init__(self):
        """sourceStart/sourceEnd が未設定の場合、start/end から初期化"""
        if self.sourceStart is None:
            self.sourceStart = self.start
        if self.sourceEnd is None:
            self.sourceEnd = self.end

    def to_dict(self) -> Dict:
        """dict 形式に変換（既存パイプラインとの互換性維持）"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Segment":
        """dict から Segment を生成

        Args:
            d: {start, end, text, sourceStart?, sourceEnd?} を含む dict

        Returns:
            Segment インスタンス

        Raises:
            KeyError: start または end が欠損している場合
        """
        return cls(
            start=d["start"],
            end=d["end"],
            text=d.get("text", ""),
            sourceStart=d.get("sourceStart"),
            sourceEnd=d.get("sourceEnd"),
        )

    @property
    def duration(self) -> float:
        """セグメントの表示時間（秒）"""
        return self.end - self.start

    @property
    def source_duration(self) -> float:
        """元動画上のセグメント時間（秒）"""
        source_end = self.sourceEnd if self.sourceEnd is not None else self.end
        source_start = self.sourceStart if self.sourceStart is not None else self.start
        return source_end - source_start


# ============================================================
# StageResult dataclass
# ============================================================

@dataclass
class StageResult:
    """ステージ実行結果"""
    stage_name: str
    success: bool
    detail: str = ""
    data: Dict = field(default_factory=dict)
    duration_seconds: float = 0.0
    retries: int = 0


# ============================================================
# PipelineContext dataclass
# ============================================================

@dataclass
class PipelineContext:
    """パイプライン全体で共有するコンテキスト"""
    video_path: str
    target_minutes: int = 20
    session_id: str = ""
    started_at: str = ""
    segments: List[Segment] = field(default_factory=list)
    selected_segments: List[Segment] = field(default_factory=list)
    preview_path: Optional[str] = None
    final_path: Optional[str] = None
    quality_score: int = 0
    # **`quality_score` の 0 は「未計測」ではない**（R1.5-C4・9周目の指摘）。
    # 既定が 0 なので、品質ゲートが一度も走らなくても「0点」がそのまま
    # `_build_result` を通り、`GET /api/pipeline/report` の「総合スコア: 0.0点」や
    # UI の「0点・❌不合格」になっていた。**条件文が名指しする
    # 「常に 0.0 になる quality_score」そのもの。**
    #
    # 0 は実際に取りうる点なので、値の側で「無い」を表そうとすると必ず
    # 取り違える（8周目に入れた `None` 判定は、生産側が 0 を出すので
    # **本番から到達できなかった**）。**「測ったかどうか」を別に持つ。**
    # 立てるのは `QualityGateWorker` だけ。
    quality_scored: bool = False
    quality_feedback: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    stage_results: List[StageResult] = field(default_factory=list)
    # テンプレート基準（themes_router → template_config から注入）
    template_id: Optional[str] = None
    template_config: Optional[Dict] = None
    # Phase 4: 無人運用 — 機能スキップ追跡
    skipped_features: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # T-031: 品質ゲート実効化 — レンダリングモード制御
    render_mode: str = "production"  # production / safe / force
    quality_gate_report: Optional[Dict] = None


# ============================================================
# Worker 基底クラス
# ============================================================

class PipelineStageWorker(ABC):
    """パイプラインステージの Worker 基底クラス"""

    def __init__(self, name: str, icon: str, index: int):
        self.name = name
        self.icon = icon
        self.index = index

    @abstractmethod
    async def execute(self, ctx: PipelineContext) -> StageResult:
        """ステージを実行"""
        pass

    def get_definition_of_done(self) -> str:
        """成功条件を返す（TaskContract 用）"""
        return f"{self.name} completed successfully"

    def verify(self, result: StageResult) -> bool:
        """結果を検証"""
        return result.success
