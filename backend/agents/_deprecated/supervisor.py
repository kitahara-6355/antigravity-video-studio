import os
import json
import logging
from typing import Literal, List, TypedDict
from pydantic import BaseModel
from google.genai import types
from google.genai.errors import APIError
from gemini_client_factory import get_gemini_client
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

# Import Model Registry
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-2.0-flash"

class Route(BaseModel):
    next: Literal["Analyst", "Strategist", "Director", "FINISH"]
    reason: str

class SupervisorAgent:
    """
    Council of Minds Supervisor
    エージェント間の対話をオーケストレーションし、次の行動を決定します。
    """
    def __init__(self):
        self.client = get_gemini_client()
        # Use Model Registry
        self.model_name = get_model("supervisor")

        
        self.system_prompt = """
        あなたは「Council of Minds (議会)」の監督官（Supervisor）です。
        以下の3つの専門家エージェントを指揮し、ユーザーの問いに対して最良の協調回答を導き出してください。

        1. **Analyst**: データ分析、競合調査、トレンド把握を担当。
        2. **Strategist**: ブランド憲法への準拠、ビジネス戦略、論理性を担当。
        3. **Director**: 映像演出、視聴体験(UX)、クリエイティブ、感情面を担当。

        ## ルール
        - ユーザーの最初の入力を受け取り、まずどのエージェントに振るべきか決定してください。
        - 各エージェントの回答を確認し、情報が十分であれば直ちに "FINISH" を選択してください。
        - **重要**: 無限ループを防ぐため、各エージェントへの指示は必要最小限に留めてください。議論が2〜3往復したら、強制的に "FINISH" して結論を出してください。
        - 決定はJSON形式で行ってください。
        """

    def route(self, messages: list) -> Route:
        """
        メッセージ履歴から次のエージェントを決定します。
        """
        # ループ防止: メッセージ数が多すぎる場合は強制終了
        if len(messages) > 10:
            return Route(next="FINISH", reason="Recursion limit safety check.")

        prompt = f"""
        これまでの対話履歴を分析し、次にどのアクションをとるべきか決定してください。
        もし必要な情報が揃っている、または議論が十分に尽くされたと判断した場合は、迷わず "FINISH" を選択してください。
        
        履歴:
        {json.dumps([m.content if hasattr(m, 'content') else str(m) for m in messages], ensure_ascii=False)}

        出力は必ず以下の形式のJSONにしてください:
        {{
            "next": "Analyst" | "Strategist" | "Director" | "FINISH",
            "reason": "なぜその選択をしたかの理由（日本語）"
        }}
        """

        if not self.client:
            logger.error("Supervisor Routing Error: Gemini client is not initialized.")
            return Route(next="FINISH", reason="Client initialization failed, finishing session.")

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            data = json.loads(response.text)
            return Route(**data)
        except APIError as e:
            logger.error(f"Supervisor Routing API Error: {e}", exc_info=True)
            return Route(next="FINISH", reason="API error, finishing session.")
        except json.JSONDecodeError as e:
            logger.error(f"Supervisor Routing JSON Parse Error: {e}", exc_info=True)
            return Route(next="FINISH", reason="Invalid response format, finishing session.")
        except Exception as e:
            logger.error(f"Supervisor Routing Unexpected Error: {e}", exc_info=True)
            return Route(next="FINISH", reason="System error, finishing session.")

if __name__ == "__main__":  # pragma: no cover
    # Test
    sup = SupervisorAgent()
    test_msg = [{"role": "user", "content": "最近再生数が落ちているので、もっと派手な演出にしたいです。"}]
    decision = sup.route(test_msg)
    print(f"Decision: {decision.next}")
    print(f"Reason: {decision.reason}")
