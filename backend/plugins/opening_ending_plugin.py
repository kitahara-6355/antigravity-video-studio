"""
Opening/Ending Plugin - OP/ED動画生成プラグイン

PROJECT_CONSTITUTION §16 準拠:
- Veo連携
- model_requirements宣言
"""
from core import Plugin, PluginPhase, ProductionContext
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


# Model Registry (SSoT: model_config.json)
def _get_model_from_registry(task: str) -> Optional[str]:
    """SSoTのmodel_registryからモデル名を取得するヘルパー"""
    import sys
    # sys.modules 内に mocked None がある場合は例外とする（テスト環境対応）
    if sys.modules.get("model_registry") is None and sys.modules.get("backend.model_registry") is None:
        raise ImportError("model_registry mocked as None")
    try:
        from model_registry import get_model as registry_get_model
        return registry_get_model(task)
    except (ImportError, AttributeError):
        try:
            from backend.model_registry import get_model as registry_get_model
            return registry_get_model(task)
        except (ImportError, AttributeError):
            return None


def _fallback_model(task: str) -> str:
    """**モデル ID を直書きしない**（R1.5-C6）。正典から引き直す。

    直書きの既定値は入替のたびに腐る。ここには 2026-10-16 に提供終了する
    2.5 系が残っていた。`model_policy` は標準ライブラリだけに依存するので、
    `model_registry` が落ちる状況でも読める。
    """
    try:
        from model_policy import resolve
    except ImportError:
        from backend.model_policy import resolve
    return resolve(task).model


def get_model(task: str) -> str:
    """モジュールレベルでのデフォルトモデル取得"""
    try:
        model = _get_model_from_registry(task)
        return model if model is not None else _fallback_model(task)
    except Exception:
        return _fallback_model(task)


class OpeningEndingPlugin(Plugin):
    """
    オープニング/エンディング動画生成プラグイン
    
    Veo 2を使用してOP/ED動画を生成する。
    """
    
    name = "opening_ending"
    phase = PluginPhase.GENERATION
    priority = 20  # サムネイルの後
    
    # モデル要件
    @property
    def model_requirements(self) -> Dict[str, Any]:
        return {
            "task": "video_generation",
            "model": get_model("opening_video"),
            "fallback": None,
            "api_type": "veo"
        }
    
    def __init__(self, generate_opening: bool = True, generate_ending: bool = True):
        self.generate_opening = generate_opening
        self.generate_ending = generate_ending
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """OP/ED動画を生成"""
        tokens = context.mood_settings
        veo_suffix = tokens.get("veo_prompt_suffix", "")
        
        if self.generate_opening:
            try:
                opening_path = self._generate_video("opening", context, veo_suffix)
                context.opening = opening_path
                self.log(f"Opening generated: {opening_path}")
            except Exception as e:
                self.log(f"Opening generation failed: {e}", level="error")
        
        if self.generate_ending:
            try:
                ending_path = self._generate_video("ending", context, veo_suffix)
                context.ending = ending_path
                self.log(f"Ending generated: {ending_path}")
            except Exception as e:
                self.log(f"Ending generation failed: {e}", level="error")
        
        return context
    
    def _build_prompt(self, video_type: str, title: str, prompt_suffix: str) -> str:
        """動画タイプに応じたプロンプトを構築"""
        if video_type == "opening":
            return f"Opening sequence for '{title}'. Dynamic intro, logo reveal. {prompt_suffix}"
        else:
            return f"Ending credits for '{title}'. Thank you message, subscribe button animation. {prompt_suffix}"
    
    def _resolve_model(self, video_type: str) -> str:
        """video_type に基づいてVeoモデル名を決定"""
        plugin_model = self.get_model()
        if plugin_model and "veo" in plugin_model.lower():
            model_task = "opening_video" if video_type == "opening" else "ending_video"
            resolved_model = _get_model_from_registry(model_task)
            if resolved_model and "veo" in resolved_model.lower():
                return resolved_model
            return plugin_model
        return "veo-2.0-generate-001"
    
    def _wait_for_operation(self, operation, timeout: int = 300, interval: int = 5) -> None:
        """非同期オペレーションの完了を待機"""
        import time
        elapsed = 0
        while not operation.done:
            if elapsed >= timeout:
                raise RuntimeError(f"Veo video generation timed out after {timeout} seconds.")
            time.sleep(interval)
            elapsed += interval
            
    def _save_video(self, operation, video_type: str, context: ProductionContext) -> Optional[str]:
        """生成された動画を保存"""
        if operation.result and operation.result.generated_videos:
            output_dir = context.output_dir / "oped"
            output_dir.mkdir(exist_ok=True)
            
            output_path = output_dir / f"{video_type}_{context.task_id}.mp4"
            
            video = operation.result.generated_videos[0]
            with open(output_path, "wb") as f:
                f.write(video.video)
            
            return str(output_path)
        return None

    def _generate_video(
        self,
        video_type: str,
        context: ProductionContext,
        prompt_suffix: str
    ) -> Optional[str]:
        """動画生成"""
        title = context.get_extension("video_title", "")
        prompt = self._build_prompt(video_type, title, prompt_suffix)
        
        try:
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
            
            model = self._resolve_model(video_type)
            
            # Veo生成（非同期）
            operation = client.models.generate_videos(
                model=model,
                prompt=prompt,
            )
            
            # 完了を待機 (最大300秒)
            self._wait_for_operation(operation)
            return self._save_video(operation, video_type, context)
                
        except Exception as e:
            logger.error(f"Veo generation failed: {e}", exc_info=True)
        
        return None
    
    def get_model(self) -> Optional[str]:
        """プラグインで使用するモデルを取得（既存テスト互換用）"""
        try:
            model = _get_model_from_registry("opening_video")
            if model is not None:
                return model
            return super().get_model()
        except Exception:
            return super().get_model()

    def can_execute(self, context: ProductionContext) -> bool:
        """タイトルがある場合のみ実行"""
        return context.get_extension("video_title") is not None
