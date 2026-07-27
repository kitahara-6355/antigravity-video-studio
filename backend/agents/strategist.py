from .agent_base import Agent, HAS_ADK
import json
from google.genai import types
from branding_manager import branding_manager

class Strategist(Agent):
    """
    Asset Name: The Strategist (Left Brain)
    Role: Brand Guardian & Business Manager
    Color: #EF4444 (Red for Discipline/Stop)
    """
    def __init__(self):
        super().__init__("Strategist", "Brand Guardian", "#EF4444")
        try:
            from model_registry import get_model
            self.model_name = get_model("strategist")
        except ImportError:
            self.model_name = "gemini-2.5-flash" 

    def _get_mode_instruction(self, mode: str) -> str:
        """指定された編集モードに応じたプロンプト用指示文を返します。"""
        if mode == "pre_production":
            return (
                "## MODE: PRE-PRODUCTION (PLANNING PHASE)\n"
                "This is a concept/planning session. Evaluate if the proposed idea, title, "
                "and thumbnail direction align with the brand target audience and tone."
            )
        return (
            "## MODE: POST-PRODUCTION (EDITING PHASE)\n"
            "This is an editing session. Evaluate if the execution (cuts, effects, pacing) "
            "aligns with the brand style and policy."
        )

    def _get_lessons_context(self, query: str) -> str:
        """過去のレッスンを取得し、プロンプトに挿入する文脈テキストを返します。"""
        learned_lessons = self.recall(query)
        if not learned_lessons:
            return ""
        return f"""
            ## LEARNED LESSONS (DO NOT VIOLATE)
            You have previously been corrected on these points. Strict adherence is required:
            {json.dumps(learned_lessons, indent=2)}
            """

    def _build_system_prompt(
        self,
        constitution: dict,
        mode_instruction: str,
        collaboration_context: str,
        lessons_context: str,
        query: str
    ) -> str:
        """入力情報を結合して、システムプロンプトを作成します。"""
        return f"""
        You are the 'Strategist' (Left Brain) of the channel '{constitution.get('channel_name')}'.
        Your role is Strict Brand Guardian & Business Manager.
        
        {mode_instruction}
        
        {collaboration_context}
        
        ## BRAND CONSTITUTION (ABSOLUTE RULES)
        - Target Audience: {constitution.get('target_audience')}
        - Tone: {constitution.get('brand_personality', {}).get('tone')}
        - Visual Style: {constitution.get('visual_identity', {}).get('style_prompt')}
        - Content Policy: {json.dumps(constitution.get('content_policy', []))}
        
        {lessons_context}


        ## YOUR MISSION
        1. Analyze the user's proposal: "{query}"
        2. Check for violations of the Constitution (especially Tone and Target Audience).
        3. If the proposal is "off-brand", DISAGREE and explain why.
        4. If it aligns but lacks business logic, offer NEUTRAL advice.
        5. If it strengthens the brand, AGREE enthusiasticlly.

        ## OUTPUT FORMAT (JSON)
        {{
            "stance": "AGREE" | "DISAGREE" | "NEUTRAL",
            "summary": "One sentence verdict (Max 20 chars for UI)",
            "detail": "Detailed reasoning (2-3 sentences). Explain WHY it fits/fails the brand.",
            "glossary": [{{ "term": "Term", "def": "Definition" }}]
        }}
        """

    def _call_llm(self, sys_prompt: str, query: str) -> str:
        """HAS_ADKの設定に従ってLLMを呼び出し、レスポンスのテキストを返します。"""
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
            return cleaned_text
        else:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=query, # Query is context for the prompt
                config=types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    response_mime_type="application/json",
                    temperature=0.3 # Low temp for logic
                )
            )
            return response.text.strip()

    def _parse_response_text(self, text: str) -> dict:
        """LLMからのテキスト応答からJSON部を抽出し、パースして辞書として返します。"""
        cleaned_text = text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:-3].strip()
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:-3].strip()
            
        result = json.loads(cleaned_text)
        
        if isinstance(result, list):
            result = result[0] if result else {}
        
        if not isinstance(result, dict):
            raise ValueError("AI response is not a valid dictionary")
            
        return result

    def process(self, input_data: dict, context: dict, council_context=None) -> dict:
        """
        Evaluates the input against the Brand Constitution.
        """
        self.notify_thinking(context)
        
        constitution = branding_manager.constitution
        query = input_data.get("text", "")
        mode = input_data.get("mode", "post_production")
        
        mode_instruction = self._get_mode_instruction(mode)
        lessons_context = self._get_lessons_context(query)
        collaboration_context = self._inject_council_findings(council_context)
        
        sys_prompt = self._build_system_prompt(
            constitution=constitution,
            mode_instruction=mode_instruction,
            collaboration_context=collaboration_context,
            lessons_context=lessons_context,
            query=query
        )

        try:
            raw_response = self._call_llm(sys_prompt, query)
            result = self._parse_response_text(raw_response)
            
            # Merge with Base Agent Data
            base = self._create_base_response()
            base.update(result)
            self.notify_done(context, base)
            return base

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"Strategist Parsing Error: {e}")
            err_res = {
                **self._create_base_response(),
                "stance": "NEUTRAL",
                "summary": "Parsing Error",
                "detail": f"Failed to parse Strategist response: {e}"
            }
            self.notify_done(context, err_res)
            return err_res
        except (KeyError, AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
            print(f"Strategist System Error: {e}")
            err_res = {
                **self._create_base_response(),
                "stance": "NEUTRAL",
                "summary": "System Error",
                "detail": f"Failed to consult the Strategist: {e}"
            }
            self.notify_done(context, err_res)
            return err_res
