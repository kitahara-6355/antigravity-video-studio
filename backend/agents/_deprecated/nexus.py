from ..agent_base import Agent
import json
import logging
from google.genai.errors import APIError

logger = logging.getLogger(__name__)


class Nexus(Agent):
    """
    The Router & Synthesizer.
    Decides which agents to summon and synthesizes their outputs.
    """
    def __init__(self):
        super().__init__("Nexus", "Router", "#888888")

    def _generate_routing_prompt(self, user_text: str) -> str:
        """ユーザーの入力テキストから、召喚すべき専門家エージェントを決定するためのプロンプトを生成する。"""
        return f"""
        あなたはAI映像制作チームのハブ（Nexus）です。
        ユーザーの発言内容を分析し、どの専門家エージェント（Analyst, Strategist, Director）を召喚すべきか判断してください。

        ## 専門家の役割
        - **Analyst**: 市場トレンド、YouTubeアナリティクス、再生数、視聴維持率の分析。
        - **Strategist**: チャンネル全体の戦略、コンセプト、憲法（ルール）の策定、長期目標。
        - **Director**: 具体的な演出、脚本、画面構成、カット割り、BGM、感情的な視聴体験。

        ## ユーザーの発言
        \"{user_text}\"

        ## ルール
        - 1つまたは複数のエージェントを選択してください。
        - 選択理由（reason）も短く日本語で記述してください。
        - 返答は必ず以下のJSON形式に従ってください。

        ## 出力形式 (JSON Only)
        {{
            "needed_agents": ["Analyst", "Strategist", "Director"],
            "reason": "具体的な選定理由"
        }}
        """

    def _get_routing_fallback_response(self, synthesis_message: str) -> dict:
        """ルーティング処理エラー時のフォールバック用レスポンスを生成する。"""
        return {
            **self._create_base_response(),
            "action": "ROUTE",
            "needed_agents": ["Strategist"],
            "synthesis": synthesis_message
        }

    def process(self, input_data: dict, context: dict) -> dict:
        """
        Nexus Logic:
        1. Analyze Intent using Gemini -> Route to specialized agents
        """
        # 未使用のcontext変数を明示的に処理してlinter警告を回避
        _ = context
        user_text = input_data.get("text", "")
        prompt = self._generate_routing_prompt(user_text)
        
        response = None
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=self.types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            result = json.loads(response.text)
            
            return {
                **self._create_base_response(),
                "action": "ROUTE",
                "needed_agents": result.get("needed_agents", []),
                "synthesis": result.get("reason", "意図に基づいて専門家をアサインしました。")
            }
        except json.JSONDecodeError as e:
            text_val = response.text if response else "None"
            logger.warning(f"Nexus Routing JSON Decode Error. response.text: {text_val}, error: {e}")
            return self._get_routing_fallback_response(
                "ルーティング判断に失敗しました（応答形式エラー）。Strategistが代表して対応します。"
            )
        except APIError as e:
            logger.error(f"Nexus Routing API Error: {e}", exc_info=True)
            return self._get_routing_fallback_response(
                "ルーティング判断に失敗しました（APIエラー）。Strategistが代表して対応します。"
            )
        except (TypeError, ValueError, AttributeError) as e:
            logger.error(f"Nexus Routing Input/Configuration Error: {e}", exc_info=True)
            return self._get_routing_fallback_response(
                "ルーティング判断に失敗しました（設定またはデータ形式のエラー）。Strategistが代表して対応します。"
            )

    def _generate_synthesis_prompt(self, debate_summary: str) -> str:
        """議会エージェントからの議論要約結果から、統合提案プロンプトを生成する。"""
        return f"""
        あなたはAI映像制作チームの「Nexus（統合知）」です。
        以下の各専門家エージェントによる議論の結果を統合し、チャンネル主（議長）に対する具体的かつ建設的な「統合提案（案）」を作成してください。

        ## 各専門家の所見
        {debate_summary}

        ## ルール
        - 各専門家（Analyst, Strategist, Director）の意見の対立点や合意点を整理してください。
        - チャンネル憲法に準拠し、かつ具体的で実行可能なアクションプランを提示してください。
        - ユーザーが「承認（Gavel）」しやすく、かつ内容に納得感がある文章（日本語）にしてください。

        ## 出力形式 (JSON Only)
        {{
            "proposal": "統合された具体的な提案内容（150字程度）",
            "summary": "要点のまとめ（1-2行）",
            "options": ["Approve", "Reject"]
        }}
        """

    def _get_synthesis_fallback_response(self, proposal_message: str) -> dict:
        """統合提案エラー時のフォールバック用レスポンスを生成する。"""
        return {
            "type": "SYNTHESIS",
            "proposal": proposal_message,
            "options": ["Approve", "Reject"]
        }

    def synthesize(self, council_responses: list) -> dict:
        """
        議会の議論結果を統合し、議長（ユーザー）への最終提案を作成します。
        """
        if not council_responses:
            return self._get_synthesis_fallback_response(
                "議論が十分に行われなかったため、明確な提案ができませんでした。"
            )

        debate_summary = json.dumps(council_responses, indent=2, ensure_ascii=False)
        prompt = self._generate_synthesis_prompt(debate_summary)
        
        response = None
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=self.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            result = json.loads(response.text)
            
            return {
                "type": "SYNTHESIS",
                "proposal": result.get("proposal", "議論を統合した結果、現在の戦略を継続することを提案します。"),
                "summary": result.get("summary", ""),
                "options": ["Approve", "Reject"]
            }
        except json.JSONDecodeError as e:
            text_val = response.text if response else "None"
            logger.warning(f"Nexus Synthesis JSON Decode Error. response.text: {text_val}, error: {e}")
            return self._get_synthesis_fallback_response(
                "議論の統合中に形式エラーが発生しましたが、概ね現状の方向性で合意しています。"
            )
        except APIError as e:
            logger.error(f"Nexus Synthesis API Error: {e}", exc_info=True)
            return self._get_synthesis_fallback_response(
                "議論の統合中にエラーが発生しました（APIエラー）。"
            )
        except (TypeError, ValueError, AttributeError) as e:
            logger.error(f"Nexus Synthesis Input/Configuration Error: {e}", exc_info=True)
            return self._get_synthesis_fallback_response(
                "議論の統合中にエラーが発生しました（設定またはデータ形式のエラー）。"
            )
