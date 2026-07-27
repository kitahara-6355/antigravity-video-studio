"""
SmartCut Strategy Service — セッション分離型 SmartCut Strategist

Sprint 4.1.2: セッション分離の実装
Sprint 4.1.3: Strategist MVP (案Z ハイブリッド型)
設計書: sprint_41_design.md §Q1 仮説B / sprint_413_strategist_mvp_design.md
憲法: §4.4 Phase 2 判断層 / §5.2 Soul Narrative / §6 議長権限

責務:
1. セッションのライフサイクル管理（作成・取得・LRU削除）
2. 各セッションに独立したSmartCutPluginインスタンスを割り当て
3. Strategist(Gemini)による戦略生成 (Sprint 4.1.3)
4. (Sprint 4.1.4) EvolutionSyncService連携
"""
import asyncio
import json
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class CutStrategy:
    """Strategist(Gemini)が生成するカット戦略

    憲法§4.4: 「Strategistの戦略的指示を受けてカット構成を決定」
    案Z: trust_scoreに基づき影響力を段階的に拡大
    """
    summary: str                              # 戦略概要
    position_weights: Dict[str, float]        # タイプ別重み {intro:1.2, body:1.0, ...}
    brand_alignment_score: float              # 0.0-1.0
    applied_philosophies: List[str]           # 注入された哲学のサマリー
    recommended_cut_rate: float               # 推奨カット率 0.0-1.0
    generated_at: str                         # ISO8601
    model_used: str                           # 使用モデル名
    trust_score: float = 0.0                  # 信頼スコア（MVP=0.0固定）

    @staticmethod
    def default() -> "CutStrategy":
        """タイムアウト/エラー時の安全なデフォルト"""
        return CutStrategy(
            summary="デフォルト戦略（Strategist未応答）",
            position_weights={"intro": 1.0, "body": 1.0, "highlight": 1.0, "outro": 1.0},
            brand_alignment_score=0.5,
            applied_philosophies=[],
            recommended_cut_rate=0.5,
            generated_at=datetime.now().isoformat(),
            model_used="default",
            trust_score=0.0,
        )


@dataclass
class SmartCutSession:
    """セッション単位のSmartCut状態管理

    各セッションが独立したSmartCutPluginインスタンスを保持し、
    並行セッション間でのState競合を防止する。

    Phase 4拡張ポイント:
    - strategy: CutStrategy (Sprint 4.1.3 で具体化済み)
    - evolution_sync: EvolutionSyncService参照 (Sprint 4.1.4 で追加)
    """
    session_id: str
    plugin: Any = None  # SmartCutPlugin — _create_session() で初期化
    strategy: Optional["CutStrategy"] = None  # Sprint 4.1.3: CutStrategy型
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)

    def touch(self):
        """アクセス時刻を更新（LRU管理用）"""
        self.last_accessed = time.time()

    @property
    def is_initialized(self) -> bool:
        """SmartCutContextが初期化済みか"""
        return self.plugin is not None and self.plugin._context is not None

    @property
    def context(self):
        """SmartCutPlugin内のcontextへのショートカット"""
        if self.plugin is None:
            return None
        return self.plugin._context

    @context.setter
    def context(self, value):
        """SmartCutPlugin内のcontextを設定"""
        if self.plugin is not None:
            self.plugin._context = value


class SmartCutStrategyService:
    """セッション分離型 SmartCut Strategist Service

    設計書: sprint_41_design.md §Q1 仮説B
    憲法: §4.4 Phase 2 判断層 / §6 議長権限

    Router移行ガイド (Sprint 4.1.3以降):
        # Before: グローバルシングルトン
        smart_cut = _get_smart_cut()

        # After: セッション経由
        smart_cut = strategy_service.get_plugin(session_id)
    """

    def __init__(self, max_sessions: int = 10):
        self._sessions: Dict[str, SmartCutSession] = {}
        self._max_sessions = max_sessions

    def get_or_create_session(self, session_id: str) -> SmartCutSession:
        """セッションを取得、または新規作成

        max_sessions超過時はLRU(最古アクセス)のセッションを削除。
        """
        if session_id not in self._sessions:
            if len(self._sessions) >= self._max_sessions:
                self._evict_oldest()
            self._sessions[session_id] = self._create_session(session_id)
            logger.info(f"[StrategyService] Created session: {session_id}")

        session = self._sessions[session_id]
        session.touch()
        return session

    def _create_session(self, session_id: str) -> SmartCutSession:
        """新しいセッションを作成（SmartCutPlugin付き）"""
        from plugins.smart_cut_plugin import SmartCutPlugin
        plugin = SmartCutPlugin()
        return SmartCutSession(session_id=session_id, plugin=plugin)

    def _evict_oldest(self):
        """LRU方式で最古セッションを削除"""
        if not self._sessions:
            return
        oldest_id = min(
            self._sessions,
            key=lambda k: self._sessions[k].last_accessed
        )
        logger.info(f"[StrategyService] Evicted oldest session: {oldest_id}")
        del self._sessions[oldest_id]

    def get_session(self, session_id: str) -> Optional[SmartCutSession]:
        """既存セッションを取得（なければNone）"""
        session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    def get_plugin(self, session_id: str):
        """Router移行用ヘルパー: session_id → SmartCutPlugin

        Router側の変更を最小化するため、プラグインインスタンスを直接返す。
        _get_smart_cut() のドロップイン置換として使用可能。
        """
        session = self.get_or_create_session(session_id)
        return session.plugin

    def remove_session(self, session_id: str) -> bool:
        """セッションを明示的に削除"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"[StrategyService] Removed session: {session_id}")
            return True
        return False

    @property
    def session_count(self) -> int:
        """アクティブセッション数"""
        return len(self._sessions)

    @property
    def session_ids(self) -> List[str]:
        """アクティブセッションIDのリスト"""
        return list(self._sessions.keys())

    @property
    def max_sessions(self) -> int:
        """最大セッション数"""
        return self._max_sessions

    # ─────────────────────────────────────────────
    # Sprint 4.1.3: Strategist MVP (案Z)
    # ─────────────────────────────────────────────

    async def generate_strategy(
        self, session_id: str, evolution_log_path: Path = None
    ) -> CutStrategy:
        """Strategist(Gemini)によるカット戦略生成

        §4.4: SmartCut実行前にStrategistが戦略を提案
        §5.2: evolution_logの全哲学をプロンプトに注入
        30秒タイムアウト → CutStrategy.default()
        """
        # 1. evolution_logから哲学を読み込み
        philosophies = self._load_philosophies(evolution_log_path)
        integrated = self._load_integrated_philosophy(evolution_log_path)

        # 2. プロンプト構築（哲学注入）
        prompt = self._build_strategy_prompt(philosophies, integrated)

        # 3. ModelRegistry経由でモデル取得（§14.1）
        from model_registry import get_model
        model_name = get_model("strategist")

        # 4. Gemini呼出し（30秒タイムアウト）
        try:
            async with asyncio.timeout(30):
                strategy = await self._call_gemini(model_name, prompt)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("[Strategist] 30秒タイムアウト → デフォルト戦略")
            strategy = CutStrategy.default()
        except (ImportError, AttributeError, OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error(f"[Strategist] エラー → デフォルト戦略: {e}")
            strategy = CutStrategy.default()

        # 5. セッションにstrategyを保存
        session = self.get_or_create_session(session_id)
        session.strategy = strategy
        return strategy

    def _load_evolution_log(self, evolution_log_path: Optional[Path] = None) -> Dict[str, Any]:
        """evolution_log.json からデータを読み込む共通ヘルパー"""
        path = evolution_log_path or (
            Path(__file__).parent.parent / "branding" / "evolution_log.json"
        )
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[Strategist] 哲学データロード失敗: {e}")
            return {}

    def _load_philosophies(self, evolution_log_path: Optional[Path] = None) -> List[Dict]:
        """evolution_logからphilosophiesを読み込み"""
        data = self._load_evolution_log(evolution_log_path)
        return data.get("philosophies", [])

    def _load_integrated_philosophy(self, evolution_log_path: Optional[Path] = None) -> str:
        """evolution_logからintegrated_philosophyを読み込み"""
        data = self._load_evolution_log(evolution_log_path)
        return data.get("integrated_philosophy", "")

    def _build_strategy_prompt(self, philosophies: List[Dict], integrated: str) -> str:
        """Strategistへのプロンプトを構築（哲学注入）"""
        return f"""あなたはAntigravity Video Studioの戦略家(Strategist)です。
ブランド憲法の守護者として、カット戦略を提案してください。

## 統合哲学
{integrated}

## 演出哲学の歴史（直近20件）
{json.dumps(philosophies[-20:], ensure_ascii=False, indent=2)}

## 出力形式（JSON）
{{
  "summary": "戦略の概要（日本語、1-2文）",
  "position_weights": {{"intro": 1.0, "body": 1.0, "highlight": 1.0, "outro": 1.0}},
  "brand_alignment_score": 0.85,
  "recommended_cut_rate": 0.5
}}

## 制約
- position_weightsの各値は0.5〜2.0の範囲
- brand_alignment_scoreは0.0〜1.0の範囲
- 哲学に基づいた根拠をsummaryに含めること
"""

    async def _call_gemini(self, model_name: str, prompt: str) -> CutStrategy:
        """Gemini APIを呼び出して戦略を生成"""
        from gemini_client_factory import get_gemini_client
        client = get_gemini_client()
        if not client:
            logger.warning("[Strategist] Geminiクライアント取得失敗 → デフォルト戦略")
            return CutStrategy.default()

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=prompt
        )
        return self._parse_response(response, model_name)

    def _extract_json_text(self, response_text: str) -> str:
        """レスポンス内のマークダウンコードブロック等からJSON文字列を抽出"""
        text = response_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()

    def _clamp_brand_alignment_score(self, raw_score: Any) -> float:
        """ブランドアライメントスコアを 0.0 - 1.0 に制限"""
        try:
            score = float(raw_score)
            return max(0.0, min(1.0, score))
        except (TypeError, ValueError):
            return 0.5

    def _parse_response(self, response, model_name: str) -> CutStrategy:
        """GeminiレスポンスをパースしてCutStrategyを生成"""
        try:
            response_text = response.text
            json_text = self._extract_json_text(response_text)
            data = json.loads(json_text)

            raw_alignment_score = data.get("brand_alignment_score", 0.5)
            brand_alignment_score = self._clamp_brand_alignment_score(raw_alignment_score)

            return CutStrategy(
                summary=data.get("summary", "AI生成戦略"),
                position_weights=data.get("position_weights", {
                    "intro": 1.0, "body": 1.0, "highlight": 1.0, "outro": 1.0
                }),
                brand_alignment_score=brand_alignment_score,
                applied_philosophies=[],
                recommended_cut_rate=float(data.get("recommended_cut_rate", 0.5)),
                generated_at=datetime.now().isoformat(),
                model_used=model_name,
                trust_score=0.0,  # MVP: 常に0.0
            )
        except (json.JSONDecodeError, KeyError, ValueError, AttributeError) as e:
            logger.warning(f"[Strategist] レスポンスパース失敗 → デフォルト戦略: {e}")
            return CutStrategy.default()

    async def resolve_session_thumbnail_task(self, task_id: str) -> str:
        """
        StageBoundAgent の process_func として動作する、セッションに紐付いた非同期サムネイル生成タスク処理
        品質自動化規約（1280x720以上, 16:9, <4MB, Pillow正常ロード）を検証します。
        """
        import json
        import asyncio
        from pathlib import Path
        from combined_overlay import CombinedOverlay

        output_dir = Path(getattr(self, "output_dir", None) or "backend/temp_thumbnails")
        output_path = output_dir / f"{task_id}.png"
        
        width = getattr(self, "width", 1280)
        height = getattr(self, "height", 720)
        text = getattr(self, "text", "Session Thumbnail")
        
        overlay = CombinedOverlay()
        await asyncio.to_thread(
            overlay.generate_thumbnail,
            output_path,
            width=width,
            height=height,
            text=text
        )
        
        # 品質検証の実行
        result_info = await asyncio.to_thread(overlay.validate_thumbnail, output_path)
        return json.dumps(result_info)
