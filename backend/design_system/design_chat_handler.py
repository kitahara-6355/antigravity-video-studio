"""
Design Chat Handler - AIチャットによるデザイントークン更新

PROJECT_CONSTITUTION §17.3 準拠:
- チャット指示でのトークン更新
- 自然言語解析
"""
from typing import Dict, Any, Optional, Tuple
import json
import logging
import os

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


class DesignChatHandler:
    """
    デザインチャットハンドラー
    
    AIチャットからの指示を解析し、デザイントークンを更新する。
    
    使用例:
        handler = DesignChatHandler()
        result = handler.process_command("エレガントのプライマリカラーをゴールドに変更")
    """
    
    # サポートするコマンドパターン
    COMMAND_PATTERNS = {
        "color": ["カラー", "色", "color", "palette"],
        "typography": ["フォント", "文字", "font", "typography", "タイポ"],
        "motion": ["アニメーション", "動き", "motion", "transition", "トランジション"],
        "prompt": ["プロンプト", "prompt", "サフィックス", "suffix"]
    }
    
    MOOD_PATTERNS = {
        "elegant": ["エレガント", "elegant", "上品", "elegance"],
        "dynamic": ["ダイナミック", "dynamic", "活発", "energetic"],
        "dramatic": ["ドラマチック", "dramatic", "劇的", "epic"]
    }
    
    COLOR_MAPPING = {
        "ゴールド": "#D4AF37",
        "シルバー": "#C0C0C0",
        "ネイビー": "#2C3E50",
        "レッド": "#E74C3C",
        "ブルー": "#3498DB",
        "パープル": "#8B5CF6",
        "グリーン": "#27AE60",
        "ブラック": "#1A1A1A",
        "ホワイト": "#FFFFFF"
    }
    
    def __init__(self):
        self._design_token_manager = None
    
    @property
    def design_token_manager(self):
        """遅延ロード"""
        if self._design_token_manager is None:
            from design_system import design_token_manager
            self._design_token_manager = design_token_manager
        return self._design_token_manager
    
    def process_command(self, command: str) -> Dict[str, Any]:
        """
        コマンドを処理
        
        Args:
            command: ユーザーからのチャットコマンド
        
        Returns:
            処理結果
        """
        logger.info(f"Processing design command: {command}")
        
        # AIで意図を解析
        parsed = self._parse_with_ai(command)
        
        if not parsed.get("valid"):
            return {
                "status": "error",
                "message": "コマンドを解析できませんでした",
                "command": command
            }
        
        # トークン更新を実行
        mood = parsed.get("mood", "elegant")
        updates = parsed.get("updates", {})
        
        if not updates:
            return {
                "status": "error",
                "message": "更新内容が見つかりませんでした",
                "parsed": parsed
            }
        
        result = self.design_token_manager.update_tokens(
            mood=mood,
            updates=updates,
            source="chat",
            reason=command
        )
        
        return {
            "status": "success",
            "message": f"デザイントークンを更新しました（ムード: {mood}）",
            "updates": updates,
            "parsed": parsed
        }
    
    def _parse_with_ai(self, command: str) -> Dict[str, Any]:
        """AIで意図を解析"""
        text = ""
        try:
            from google import genai
            
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
            if client is None:
                logger.warning("Gemini client is None. Falling back to simple parsing.")
                return self._parse_simple(command)
            
            prompt = f"""
以下のコマンドを解析し、デザイントークンの更新内容をJSON形式で出力してください。

コマンド: {command}

利用可能なムード: elegant, dynamic, dramatic
利用可能な設定:
- color_palette.primary, color_palette.secondary, color_palette.background, color_palette.text
- typography.title_font, typography.body_font, typography.title_size, typography.body_size
- motion.transition_duration, motion.easing
- imagen_prompt_suffix, veo_prompt_suffix

出力形式:
{{
    "valid": true,
    "mood": "ムード名",
    "updates": {{
        "更新するキー": "新しい値"
    }}
}}

解析できない場合:
{{"valid": false, "reason": "理由"}}
"""
            
            try:
                from google.genai.errors import APIError
            except ImportError:
                class APIError(Exception):
                    pass

            response = client.models.generate_content(
                model=get_model("branding"),
                contents=prompt
            )
            
            if response is None or not hasattr(response, "text"):
                logger.warning("AI response is invalid or missing text attribute. Falling back to simple parsing.")
                return self._parse_simple(command)
                
            text = response.text
            if text is None:
                logger.warning("AI response text is None. Falling back to simple parsing.")
                return self._parse_simple(command)

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            return json.loads(text.strip())
            
        except ImportError as ie:
            logger.warning(f"AI module/factory import failed: {ie}. Falling back to simple parsing.")
            return self._parse_simple(command)
        except json.JSONDecodeError as jde:
            logger.error(f"AI parsing returned invalid JSON: {jde}. Raw text: {text}")
            return self._parse_simple(command)
        except APIError as ae:
            logger.error(f"Gemini API call failed: {ae}. Falling back to simple parsing.")
            return self._parse_simple(command)
        except AttributeError as attr_err:
            logger.error(f"AI response object missing expected attribute: {attr_err}. Falling back to simple parsing.")
            return self._parse_simple(command)
        except Exception as e:
            logger.exception(f"AI parsing failed due to unexpected error: {e}")
            try:
                from agents.memory.technical_debt import technical_debt_store
                technical_debt_store.register_debt(
                    category="ACCEPTED_SAFETY",
                    file_path="backend/design_system/design_chat_handler.py",
                    line_number=188,
                    pattern="except Exception as e: AI parsing unexpected error fallback",
                    cause_pattern="DP-02",
                    fix_pattern="具体的な例外が発生した場合は個別のexceptブロックを追加する",
                    registered_by="Phase 33 bug_hunter",
                    notes=f"AI解析での最終予期せぬエラーのセーフティガード: {str(e)[:100]}"
                )
            except Exception as td_err:
                logger.warning(f"Failed to register technical debt: {td_err}")
            return self._parse_simple(command)
    
    def _parse_simple(self, command: str) -> Dict[str, Any]:
        """簡易解析（フォールバック）"""
        result = {"valid": False, "mood": "elegant", "updates": {}}
        
        # ムード検出
        for mood, patterns in self.MOOD_PATTERNS.items():
            if any(p in command for p in patterns):
                result["mood"] = mood
                break
        
        # カラー更新検出
        for color_name, hex_code in self.COLOR_MAPPING.items():
            if color_name in command:
                if "プライマリ" in command or "primary" in command.lower():
                    result["updates"]["color_palette"] = {"primary": hex_code}
                    result["valid"] = True
                elif "セカンダリ" in command or "secondary" in command.lower():
                    result["updates"]["color_palette"] = {"secondary": hex_code}
                    result["valid"] = True
        
        return result
    
    def get_current_tokens_summary(self, mood: str = "elegant") -> str:
        """現在のトークンサマリーを取得"""
        tokens = self.design_token_manager.get_tokens(mood)
        
        lines = [f"## {mood.capitalize()} デザイントークン\n"]
        
        for key, value in tokens.items():
            if isinstance(value, dict):
                lines.append(f"### {key}")
                for k, v in value.items():
                    lines.append(f"- {k}: `{v}`")
            else:
                lines.append(f"- {key}: `{value}`")
        
        return "\n".join(lines)


# シングルトンインスタンス
design_chat_handler = DesignChatHandler()
