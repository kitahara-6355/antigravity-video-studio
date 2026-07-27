from typing import TypedDict, List, Optional, Literal, Union
from .agent_base import Agent, HAS_ADK
import json
import logging
from google import genai
from google.genai import types
from google.genai.errors import APIError
from branding_manager import branding_manager
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# --- カスタム例外定義（設計ステップ 1/3） ---
class DirectorError(Exception):
    """Directorモジュール全体の基底例外"""
    pass

class DirectorValidationError(DirectorError):
    """入力データやパラメータの検証エラー"""
    pass

class DirectorLLMError(DirectorError):
    """LLM呼び出し失敗、またはレスポンス解析失敗"""
    pass

# --- 型定義（設計ステップ 1/3） ---
class DirectorInput(TypedDict, total=False):
    text: str  # 演出の対象となるテキスト
    mode: Literal["pre_production", "post_production"]  # 制作フェーズ

class DirectorResponse(TypedDict):
    agent: str  # エージェント名 ("Director")
    role: str  # 役割名
    color: str  # UIカラーコード
    timestamp: float  # 処理タイムスタンプ
    stance: Literal["AGREE", "DISAGREE", "NEUTRAL"]  # 賛否スタンス
    summary: str  # 一言サマリー
    detail: str  # 演出の詳細アドバイス
    glossary: List[str]  # 専門用語リスト

class Director(Agent):
    """
    Asset Name: The Director (Right Brain)
    Role: Creative Director (UX & Emotion)
    Color: #3B82F6 (Blue for Tech/Flow)
    """
    def __init__(self):
        super().__init__("Director", "Creative Director", "#3B82F6")
        if getattr(self, "model_name", None) == "gemini-2.5-flash":
            return
        try:
            from model_registry import get_model
            self.model_name = get_model("director")
        except (ImportError, ModuleNotFoundError) as e:
            logger.info(f"model_registry not found, falling back to default model: {e}")
            self.model_name = "gemini-2.5-flash"
        except (KeyError, ValueError, TypeError, RuntimeError) as e:
            logger.warning(f"Failed to load model from registry, falling back to default: {e}")
            self.model_name = "gemini-2.5-flash"
        except Exception as e:
            logger.error(f"Unexpected error loading model from registry, falling back to default: {e}", exc_info=True)
            self.model_name = "gemini-2.5-flash"
            self._register_tdr(e)

    def process(self, input_data: Union[dict, DirectorInput], context: dict, council_context: Optional[dict] = None) -> Union[dict, DirectorResponse]:
        """
        Evaluates the input from a Creative/UX perspective.

        Args:
            input_data (DirectorInput): 入力データ。クエリテキストやモードを含む。
            context (dict): 実行コンテキスト。WebSocket通知等で使用。
            council_context (Optional[dict]): 評議会の他エージェントの合議コンテキスト。

        Returns:
            DirectorResponse: 演出評価結果の構造化レスポンス。

        Raises:
            DirectorValidationError: input_data の検証に失敗した場合
            DirectorLLMError: LLMの処理に失敗した場合
            HTTPException: FastAPI of HTTP exception
        """
        if not isinstance(context, dict):
            context = {}
        
        try:
            self.notify_thinking(context)
            
            # 1. 入力データのバリデーション
            if not isinstance(input_data, dict):
                raise DirectorValidationError("Failed to consult the Director (Validation): input_data must be a dictionary")
            
            mode = input_data.get("mode")
            if mode not in (None, "pre_production", "post_production"):
                raise DirectorValidationError(f"Failed to consult the Director (Validation): Invalid mode '{mode}'")
            
            query = input_data.get("text")
            if query is None:
                query = ""
            if not isinstance(query, str):
                raise DirectorValidationError("Failed to consult the Director (Validation): query text must be a string")
            
            if not query:
                logger.warning("Director process query text is empty")
            
            sys_prompt = self._build_system_prompt(input_data, council_context)
            response_text = self._call_llm(query, sys_prompt)
            result = self._parse_and_validate_response(response_text)
            
            base = self._create_base_response()
            base.update(result)
            # エージェントの基本メタデータがLLM出力によって上書きされるのを防ぐ
            base["agent"] = self.name
            base["role"] = self.role
            base["color"] = self.color
            if "glossary" not in base or not isinstance(base.get("glossary"), list):
                base["glossary"] = []
            self.notify_done(context, base)
            return base

        except HTTPException:
            raise
        except DirectorValidationError as e:
            logger.warning(f"Director Validation Error: {e}")
            err_res = {
                **self._create_base_response(),
                "stance": "NEUTRAL",
                "summary": "Validation Error",
                "detail": str(e)
            }
            self.notify_done(context, err_res)
            return err_res
        except DirectorLLMError as e:
            logger.error(f"Director LLM Error: {e}", exc_info=True)
            self._register_tdr(e)
            err_res = {
                **self._create_base_response(),
                "stance": "NEUTRAL",
                "summary": "System Error",
                "detail": f"Failed to consult the Director: {e}"
            }
            self.notify_done(context, err_res)
            return err_res
        except ValueError as e:
            logger.error(f"Director Value Error: {e}", exc_info=True)
            self._register_tdr(e)
            err_res = {
                **self._create_base_response(),
                "stance": "NEUTRAL",
                "summary": "System Error",
                "detail": f"Failed to consult the Director (Value Error): {e}"
            }
            self.notify_done(context, err_res)
            return err_res
        except Exception as e:
            logger.error(f"Director Unexpected Error: {e}", exc_info=True)
            self._register_tdr(e)
            err_res = {
                **self._create_base_response(),
                "stance": "NEUTRAL",
                "summary": "System Error",
                "detail": f"Failed to consult the Director: {e}"
            }
            self.notify_done(context, err_res)
            return err_res

    def _register_tdr(self, e: Exception) -> None:
        """TDRに技術負債を登録する共通ヘルパーメソッド"""
        try:
            import sys
            import traceback
            # 元の原因例外がある場合はそれを辿る
            cause_err = e
            while cause_err.__cause__:
                cause_err = cause_err.__cause__
            tb = cause_err.__traceback__ or sys.exc_info()[2]
            err_line = 56
            err_file = "agents/director.py"
            if not tb:
                try:
                    import inspect
                    frame = inspect.currentframe()
                    if frame and frame.f_back:
                        caller_frame = frame.f_back
                        err_line = caller_frame.f_lineno
                        err_file = caller_frame.f_code.co_filename
                except Exception as ie:
                    logger.warning(f"Failed to inspect caller frame for TDR: {ie}")
            if tb:
                tb_info = traceback.extract_tb(tb)
                if tb_info:
                    target_frame = None
                    for frame in reversed(tb_info):
                        if "director.py" in frame.filename or "agents" in frame.filename:
                            target_frame = frame
                            break
                    if not target_frame:
                        target_frame = tb_info[-1]
                        
                    err_file = target_frame.filename
                    err_line = target_frame.lineno
                    
                    try:
                        import os
                        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if os.path.isabs(err_file):
                            rel_path = os.path.relpath(err_file, backend_dir).replace("\\", "/")
                            if not rel_path.startswith(".."):
                                err_file = rel_path
                            else:
                                project_root = os.path.dirname(backend_dir)
                                rel_project = os.path.relpath(err_file, project_root).replace("\\", "/")
                                if not rel_project.startswith(".."):
                                    err_file = rel_project
                    except Exception as pe:
                        logger.warning(f"Failed to resolve project relative path for {err_file}: {pe}")
                        
                    if "agents" in err_file:
                        err_file = "agents" + err_file.split("agents", 1)[1]
                    err_file = err_file.replace("\\", "/")

            from .memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            store.register_debt(
                category="IMPORTANT_SERVICE",
                file_path=err_file,
                line_number=err_line,
                pattern="process try-except block",
                notes=f"Error ({type(cause_err).__name__}) in Director process: {str(cause_err)}"
            )
        except Exception as tde:
            logger.error(f"Failed to register technical debt in Director process: {tde}", exc_info=True)

    def _build_system_prompt(self, input_data: dict, council_context) -> str:
        """Builds the system prompt with context and branding rules."""
        constitution = getattr(branding_manager, "constitution", {}) or {}
        if not isinstance(constitution, dict):
            constitution = {}
            
        query = input_data.get("text") or ""
        mode = input_data.get("mode") or "post_production"
        
        if mode == "pre_production":
            mode_instruction = (
                '## MODE: PRE-PRODUCTION (PLANNING PHASE)\n'
                'This is a concept/planning session. Focus on the visual POTENTIAL of the idea. '
                'Suggest visual hooks, thumbnail directions, and overall aesthetic approach for the topic.'
            )
        else:
            mode_instruction = (
                '## MODE: POST-PRODUCTION (EDITING PHASE)\n'
                'This is an editing session. Focus on concrete editing techniques, pacing, '
                'jump cuts, B-rolls, and graphics implementation.'
            )

        # 0. Recall Past Lessons
        learned_lessons = self.recall(query)
        lessons_context = ""
        if learned_lessons:
            lessons_context = f"""
            ## STYLE MEMORY (USER PREFERENCES)
            The user has previously given this feedbacks. Prioritize these over default style:
            {json.dumps(learned_lessons, indent=2)}
            """
        
        # 0.5 Inter-Agent Collaboration Insight
        collaboration_context = self._inject_council_findings(council_context)

        channel_name = constitution.get('channel_name') or "Creative Channel"
        visual_identity = constitution.get('visual_identity') if isinstance(constitution.get('visual_identity'), dict) else {}
        style_prompt = (visual_identity.get('style_prompt') if visual_identity else None) or "Modern Creative Style"
        brand_personality = constitution.get('brand_personality') if isinstance(constitution.get('brand_personality'), dict) else {}
        brand_tone = (brand_personality.get('tone') if brand_personality else None) or "Friendly and engaging"

        sys_prompt = f"""
        You are the 'Director' (Right Brain) of the channel '{channel_name}'.
        Your role is Creative Director (UX, Pacing, Content Quality).
        
        {mode_instruction}
        
        {collaboration_context}
        
        ## BRAND VISUALS
        - Style: {style_prompt}
        - Tone: {brand_tone}
        
        {lessons_context}


        ## YOUR MISSION
        1. Analyze the user's proposal: "{query}"
        2. Focus strictly on "Viewer Experience" (Is it boring? Is it clear? Is it cool?).
        3. Ignore business metrics (leave that to the Strategist).
        4. Provide concrete creative advice.

        ## OUTPUT FORMAT (JSON)
        {{
            "stance": "AGREE" | "DISAGREE" | "NEUTRAL",
            "summary": "One sentence creative verdict",
            "detail": "Detailed creative advice. Focus on 'How to make it cooler'.",
            "glossary": []
        }}
        """
        return sys_prompt

    def _call_llm(self, query: str, sys_prompt: str) -> str:
        """Invokes the AI model (using either ADK Agent or GenAI client)."""
        try:
            if HAS_ADK:
                from google.adk.agents import Agent as ADKAgent
                from google.adk.runners import InMemoryRunner
                from google.adk.agents.run_config import RunConfig
                
                adk_agent = ADKAgent(
                    name=self.name,
                    model=self.model_name,
                    instruction=sys_prompt,
                    description=self.role
                )
                runner = InMemoryRunner(agent=adk_agent, app_name=f"app_{self.name.lower()}")
                runner.auto_create_session = True
                
                run_config = RunConfig(max_llm_calls=5)
                content = types.Content(
                    role="user",
                    parts=[types.Part(text=query)]
                )
                
                cleaned_text = ""
                for event in runner.run(
                    user_id="user",
                    session_id=f"session_{self.name.lower()}",
                    new_message=content,
                    run_config=run_config
                ):
                    if event.is_final_response() and event.content:
                        for part in event.content.parts:
                            if part.text:
                                cleaned_text += part.text
                if not cleaned_text.strip():
                    raise DirectorLLMError("ADK LLM returned an empty response")
                return cleaned_text
            else:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=query,
                    config=types.GenerateContentConfig(
                        system_instruction=sys_prompt,
                        response_mime_type="application/json",
                        temperature=0.7 
                    )
                )
                try:
                    resp_text = response.text if response else None
                except ValueError as ve:
                    raise DirectorLLMError(f"Failed to retrieve text from Gemini response (possibly blocked): {ve}") from ve

                if not response or not resp_text or not resp_text.strip():
                    raise DirectorLLMError("LLM returned an empty or invalid response")
                return resp_text.strip()
        except (HTTPException, ValueError):
            raise
        except APIError as e:
            raise DirectorLLMError(f"Failed to consult the Director due to Gemini API Error: {e}") from e
        except Exception as e:
            raise DirectorLLMError(f"Failed to consult the Director due to unexpected LLM error: {e}") from e

    def _parse_and_validate_response(self, response_text: str) -> dict:
        """Cleans response text, parses JSON, and validates that it is a dict."""
        try:
            if not isinstance(response_text, str):
                raise DirectorLLMError("AI response must be a string")
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```json"):
                if cleaned_text.endswith("```"):
                    cleaned_text = cleaned_text[7:-3].strip()
            elif cleaned_text.startswith("```"):
                if cleaned_text.endswith("```"):
                    cleaned_text = cleaned_text[3:-3].strip()
                
            try:
                result = json.loads(cleaned_text)
            except json.JSONDecodeError:
                import re
                result = None
                # ロバストな JSON 抽出: 非貪欲マッチでまず { ... } の全候補を試みる
                matches = re.findall(r"({.*?})", cleaned_text, re.DOTALL)
                for m in matches:
                    try:
                        parsed = json.loads(m)
                        if isinstance(parsed, dict):
                            result = parsed
                            break
                    except json.JSONDecodeError:
                        continue
                
                # それでもダメなら貪欲マッチで最大の塊を試みる
                if not isinstance(result, dict):
                    match = re.search(r"({.*})", cleaned_text, re.DOTALL)
                    if match:
                        try:
                            result = json.loads(match.group(1))
                        except json.JSONDecodeError as e:
                            raise DirectorLLMError(f"AI response contains invalid JSON structure: {e}")
                    else:
                        raise DirectorLLMError("No JSON structure found in AI response")
            
            # リストが返された場合、最初の辞書要素を探索する
            if isinstance(result, list):
                found_dict = {}
                for item in result:
                    if isinstance(item, dict):
                        found_dict = item
                        break
                result = found_dict
            
            if not isinstance(result, dict):
                raise DirectorLLMError("AI response is not a valid dictionary")
                
            # Validates stance key and normalizes if unknown
            stance = result.get("stance")
            if stance not in ("AGREE", "DISAGREE", "NEUTRAL"):
                logger.warning(f"Invalid stance '{stance}' received from AI. Defaulting to 'NEUTRAL'.")
                stance = "NEUTRAL"
                result["stance"] = "NEUTRAL"
                
            # Ensure summary and detail exist with appropriate values based on stance
            if "summary" not in result or not result["summary"] or not isinstance(result["summary"], str):
                if "summary" in result:
                    logger.warning("Invalid or empty 'summary' received from AI. Setting default based on stance.")
                if stance == "AGREE":
                    result["summary"] = "演出方針に同意します (Approved)"
                elif stance == "DISAGREE":
                    result["summary"] = "演出の修正を推奨します (Revision recommended)"
                else:
                    result["summary"] = "No opinion"
                
            if "detail" not in result or not result["detail"] or not isinstance(result["detail"], str):
                if "detail" in result:
                    logger.warning("Invalid or empty 'detail' received from AI. Setting default.")
                result["detail"] = "演出の詳細アドバイスは提供されませんでした。"
                
            if "glossary" in result:
                if not isinstance(result["glossary"], list):
                    logger.warning("Invalid 'glossary' type in AI response. Defaulting to empty list.")
                    result["glossary"] = []
                else:
                    # Ensure all elements in glossary are strings
                    result["glossary"] = [str(item) for item in result["glossary"]]
                
            return result
        except DirectorError:
            raise
        except Exception as e:
            raise DirectorLLMError(f"Failed to parse and validate AI response: {e}") from e
