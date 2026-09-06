"""
Design System Plugin - デザインシステム適用プラグイン

PROJECT_CONSTITUTION §16, §17 準拠:
- プラグインインターフェース
- デザイントークン適用
"""
from core import Plugin, PluginPhase, ProductionContext
from typing import Dict, Any, Optional
import logging

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    # **モデル ID を直書きしない**（R1.5-C6）。正典は model_config.json で、
    # それを読む解決器が model_policy（標準ライブラリだけに依存するので
    # model_registry より落ちにくい）。直書きの既定値は入替のたびに腐り、
    # 実際それで 2026-10-16 に提供終了する 2.5 系が本番の実行経路に居座った。
    def get_model(task):
        # **import は関数の中で行う。** module 直下に置くと、`backend/` が
        # sys.path に無いときに import 自体が落ち、従来なら起動できた場面で
        # モジュールごと死ぬ（R1.5-C6・gate-verifier 2周目の指摘）
        try:
            from model_policy import resolve
        except ImportError:
            from backend.model_policy import resolve
        return resolve(task).model

logger = logging.getLogger(__name__)


class DesignSystemPlugin(Plugin):
    """
    デザインシステム適用プラグイン
    
    制作開始時にデザイントークンを読み込み、
    コンテキストに設定する。
    """
    
    name = "design_system"
    phase = PluginPhase.PRE_PROCESS
    priority = 1  # 最優先で実行
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """デザイントークンをコンテキストに適用"""
        from .design_token_manager import design_token_manager
        
        mood = context.mood
        self.log(f"Applying design tokens for mood: {mood}")
        
        # トークンを取得
        tokens = design_token_manager.get_tokens(mood)
        
        if not tokens:
            self.log(f"No design tokens found for mood '{mood}'", level="warning")
            return context
        
        # コンテキストに設定
        context.mood_settings = tokens
        
        # 個別トークンも拡張データに設定
        context.set_extension("color_palette", tokens.get("color_palette", {}))
        context.set_extension("typography", tokens.get("typography", {}))
        context.set_extension("motion", tokens.get("motion", {}))
        context.set_extension("imagen_prompt_suffix", tokens.get("imagen_prompt_suffix", ""))
        context.set_extension("veo_prompt_suffix", tokens.get("veo_prompt_suffix", ""))
        
        self.log(f"Design tokens applied: {len(tokens)} properties")
        return context
    
    def can_execute(self, context: ProductionContext) -> bool:
        """常に実行"""
        return True


class BrandConsistencyPlugin(Plugin):
    """
    ブランド整合性チェックプラグイン
    
    生成物がブランドガイドラインに沿っているかチェック。
    """
    
    name = "brand_consistency"
    phase = PluginPhase.POST_PROCESS
    priority = 50
    
    # モデル要件
    @property
    def model_requirements(self) -> Dict[str, Any]:
        """モデル要件"""
        return {
            "task": "brand_check",
            "model": get_model("branding"),
            "fallback": None,
            "api_type": "gemini"
        }
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """ブランド整合性チェック"""
        self.log("Checking brand consistency")
        
        # 現在の設定を取得
        color_palette = context.get_extension("color_palette", {})
        typography = context.get_extension("typography", {})
        
        issues = []
        
        # カラーチェック
        if not color_palette:
            issues.append("Color palette not applied")
        
        # タイポグラフィチェック
        if not typography:
            issues.append("Typography not applied")
        
        # 結果を記録
        context.set_extension("brand_check_issues", issues)
        context.set_extension("brand_check_passed", len(issues) == 0)
        
        if issues:
            self.log(f"Brand consistency issues: {len(issues)}", level="warning")
        else:
            self.log("Brand consistency check passed")
        
        return context
    
    def can_execute(self, context: ProductionContext) -> bool:
        """デザイントークンが適用されている場合"""
        return bool(context.mood_settings)
