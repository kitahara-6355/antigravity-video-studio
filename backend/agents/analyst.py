from .agent_base import Agent, HAS_ADK
import json

class Analyst(Agent):
    """
    Asset Name: The Analyst (War Room)
    Role: Data Scientist & Rival Researcher
    Color: #F59E0B (Amber/Gold for Data/Insight)
    """
    def __init__(self):
        super().__init__("Analyst", "Data Scientist", "#F59E0B")
        try:
            from model_registry import get_model
            self.model_name = get_model("analyst")
        except ImportError:
            self.model_name = "gemini-2.5-flash"

        
    def process(self, input_data: dict, context: dict, council_context=None) -> dict:
        """
        Analyst Logic:
        1. Fetch Real Stats (post) / Predict CTR (pre)
        2. Compare with Rivals (Nemesis/Benchmark) (post) / Validate against Knowledge Base (pre)
        3. Identify Gaps
        """
        self.notify_thinking(context)
        # Lazy import to avoid circular dependency
        from branding.analytics_manager import analytics_manager
        from plugins.youtube_optimizer_plugin import YouTubeOptimizerPlugin
        
        mode = input_data.get("mode", "post_production")
        
        if mode == "pre_production":
            query = input_data.get("text", "")
            if query is None:
                query = ""

            
            # Fix①: 動的CTR計算関数を呼び出し
            predicted_ctr = YouTubeOptimizerPlugin.calculate_video_ctr(query)
            
            # Fix①: Wagamama Ledgerの蒸留知識で補正（学習ループの接続）
            try:
                from wagamama_manager import wagamama_manager
                knowledge_base = wagamama_manager.ledger_data.get("knowledge_base", [])
                # 直近5件の蒸留パターンの平均信頼度でCTR補正
                if knowledge_base:
                    recent = knowledge_base[-5:]
                    avg_confidence = sum(k.get("confidence", 0.9) for k in recent) / len(recent)
                    # 信頼度が高い成功パターンが多いほど若干CTR予測を引き上げる (最大+0.5%)
                    bonus = round((avg_confidence - 0.7) * 2.5, 1)
                    predicted_ctr = round(min(15.0, predicted_ctr + bonus), 1)
            except (ImportError, AttributeError, KeyError, TypeError):
                pass  # 蒸留知識が未初期化の場合でも動作継続
            
            stance = "NEUTRAL"
            advice = f"タイトル案「{query[:15]}...」の予測CTRは {predicted_ctr}% です。3つのサムネイル案と5つのタイトルでA/Bテストを実施することを推奨します。"
            
            if predicted_ctr >= 5.0:
                stance = "AGREE"
                advice = f"予測CTRが {predicted_ctr}% と非常に高い水準です。このコンセプトでProductionへ進むことを強く推奨します。"
            elif predicted_ctr < 4.0:
                stance = "DISAGREE"
                advice = f"予測CTRが {predicted_ctr}% で基準値（4.0%）を下回っています。切り口を変えるか、より強いフックを追加してください。"
                
            result = {
                **self._create_base_response(),
                "stance": stance,
                "summary": f"予測CTR: {predicted_ctr}%",
                "detail": advice,
                "data": {"predicted_ctr": predicted_ctr},
                "glossary": []
            }
            final_res = self._run_adk_bridge(result)
            self.notify_done(context, final_res)
            return final_res
        
        # --- post_production モード ---
        # Fix③: アドバイス文を日本語に統一
        my_stats = analytics_manager.get_my_stats()
        if not isinstance(my_stats, dict):
            my_stats = {}
            
        rivals = analytics_manager.scout_rivals(my_stats)
        if not isinstance(rivals, dict):
            rivals = {}
        
        gap_subs = 0
        nemesis = rivals.get('nemesis')
        if isinstance(nemesis, dict) and 'subs' in nemesis and 'name' in nemesis:
            gap_subs = nemesis['subs'] - my_stats.get('subscribers', 0)
        else:
            nemesis = None
            
        advice = ""
        stance = "NEUTRAL"
        
        if nemesis:
            if gap_subs > 0:
                advice = f"ライバルチャンネル「{nemesis['name']}」に {gap_subs:,} 人差をつけられています。投稿頻度を高めることで差を縮められます。"
                stance = "DISAGREE"
            else:
                advice = "現在ライバルチャンネルをリードしています。このペースを維持してください。"
                stance = "AGREE"
        else:
            advice = "現在比較対象となるライバルが見つかりません。この調子でコンテンツ投稿を継続してください。"
            stance = "AGREE"
            
        result = {
            **self._create_base_response(),
            "stance": stance,
            "summary": "データ分析完了",
            "detail": advice,
            "data": {
                "my_stats": my_stats,
                "rivals": rivals
            },
            "glossary": [
                {"term": "ライバルチャンネル", "def": "あなたのチャンネルより少し数値が高い、目指すべき競合チャンネル。"},
                {"term": "投稿速度", "def": "1日あたりの登録者増加ペース。"}
            ]
        }

        final_res = self._run_adk_bridge(result)
        self.notify_done(context, final_res)
        return final_res

    def _run_adk_bridge(self, result: dict) -> dict:
        if HAS_ADK:
            from google.adk.agents import Agent as ADKAgent
            from google.adk.runners import InMemoryRunner
            from google.adk.agents.run_config import RunConfig
            from google.genai import types as genai_types
            
            input_json = json.dumps(result, ensure_ascii=False)
            sys_prompt = (
                "あなたはデータ分析を行うアナリストです。以下のデータ分析結果を入力として受け取ります。\n"
                "入力されたJSON構造をそのままパースして、再度まったく同一のJSON構造として返してください。\n"
                "追加のテキストや説明は一切含めず、純粋なJSONデータのみを出力してください。"
            )
            
            try:
                adk_agent = ADKAgent(
                    name=self.name,
                    model=self.model_name,
                    instruction=sys_prompt,
                    description=self.role
                )
                runner = InMemoryRunner(agent=adk_agent, app_name=f"app_{self.name.lower()}")
                runner.auto_create_session = True
                
                run_config = RunConfig(max_llm_calls=5)
                content = genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=input_json)]
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
                
                cleaned_text = cleaned_text.strip()
                if cleaned_text.startswith("```json"):
                    cleaned_text = cleaned_text[7:-3].strip()
                elif cleaned_text.startswith("```"):
                    cleaned_text = cleaned_text[3:-3].strip()
                
                adk_result = json.loads(cleaned_text)
                if isinstance(adk_result, dict):
                    base = self._create_base_response()
                    base.update(adk_result)
                    base["agent"] = self.name
                    base["role"] = self.role
                    base["color"] = self.color
                    return base

            except Exception as e:
                print(f"Analyst ADK Parse Error: {e}")
                
        return result

