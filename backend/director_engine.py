import os
import base64
import uuid
import time
import json
import logging
from dotenv import load_dotenv
from google.genai import types
from gemini_client_factory import get_gemini_client

# Initialize logger
logger = logging.getLogger("director_engine")

# Load API Key from .env
load_dotenv()

# Import Model Registry
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-3.6-flash"

class TaskManager:
    def __init__(self):
        self.tasks = {} 
    
    def create_task(self):
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {
            "id": task_id,
            "status": "pending",
            "result": None,
            "error": None,
            "created_at": time.time()
        }
        return task_id

    def update_task(self, task_id, status, result=None, error=None):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            if result is not None: self.tasks[task_id]["result"] = result
            if error is not None: self.tasks[task_id]["error"] = error
            
    def get_task(self, task_id):
        return self.tasks.get(task_id)

task_manager = TaskManager()

from branding_manager import branding_manager

class DirectorBrain:
    def __init__(self):
        self.client = get_gemini_client()
        if not self.client:
            print("WARNING: GOOGLE_API_KEY not found — DirectorBrain in STUB mode.")
        
        # Models - Use Model Registry
        self.chat_model = get_model("director")
        self.image_model = get_model("thumbnail")
 
        
        # --- THE DUAL BRAIN ---
        # Left Brain: Strategic Consultant (Business & Logic)
        self.persona_consultant = """
        あなたはYoutube戦略コンサルタント「Antigravity Strategist (左脳)」です。
        ユーザー（クリエイター）の「経営参謀」として、収益化とブランド構築を最優先に考えたアドバイスを行ってください。

        ## 役割 (Mission)
        1. **Numbers over Art**: 芸術性よりも「数字（再生数、維持率、CTR）」を重視する。
        2. **Brand Guardian**: 「{channel_name}」のブランド憲法（Brand Constitution）に反する企画は厳しく指摘する。
        3. **Logic Driven**: 感情論ではなく、ロジックとデータに基づいて話す。

        ## ユーザーのステータス (Biz Rank: {biz_rank})
        現在のユーザーはビジネスレベル「{biz_rank}」です。
        {biz_advice_mode}
        """

        # Right Brain: Creative Director (Art & Tech)
        self.persona_director = """
        あなたは映像監督「Antigravity Director (右脳)」です。
        ユーザー（クリエイター）の「技術指導者」として、最高の視聴体験（UX）を作るための具体的な演出指示を行ってください。

        ## 役割 (Mission)
        1. **Art over Numbers**: 数字よりも「視聴者の感情」と「没入感」を重視する。
        2. **Technical Mentor**: 具体的なカット割り、色使い、音響効果について、プロの視点で細かく指導する。
        3. **Vibe Driven**: 理屈よりも「かっこよさ」「心地よさ」を優先する。

        ## ユーザーのステータス (Tech Rank: {tech_rank})
        現在のユーザーは技術レベル「{tech_rank}」です。
        {tech_advice_mode}
        """
        
        # ============================================
        # Phase 4: Nexus 2.0 セマンティック・ディスパッチャー
        # ============================================
        self.nexus_prompt = """
あなたは「Nexus 2.0」です。ユーザーの曖昧な発言から、真の意図を解析し、最適な専門家エージェントを動的にアサインする司令塔です。

## 専門家エージェント一覧
- **Strategist（戦略家）**: ビジネス戦略、収益化、ブランド構築、市場分析
- **Director（演出家）**: 映像演出、カット割り、色彩、音響、視覚効果
- **Analyst（分析官）**: データ分析、パフォーマンス評価、品質チェック

## 意図解析ルール
1. 「もっとエモくして」→ Director（感情表現は演出の領域）
2. 「数字伸ばしたい」→ Strategist + Analyst（戦略とデータ両方必要）
3. 「品質チェックして」→ Analyst（分析の領域）
4. 「なんかイマイチ」→ 全員（曖昧なので多角的分析）

## 出力形式（JSON）
{{
    "intent": "検出された意図の要約",
    "agents": ["Agent1", "Agent2"],
    "confidence": 0.0-1.0,
    "rationale": "このエージェント選択の理由"
}}
"""

    def semantic_dispatch(self, user_input: str) -> dict:
        """
        Nexus 2.0: セマンティック・ディスパッチャー
        ユーザーの曖昧な入力から意図を解析し、最適なエージェントを動的に割り当てる
        """
        try:
            prompt = f"""
{self.nexus_prompt}

## ユーザー入力
「{user_input}」

この入力を分析し、最適なエージェントをアサインしてください。
"""
            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3  # 判断は低温で安定させる
                )
            )
            
            result = json.loads(response.text)
            
            # ログ出力
            nexus_logger = logging.getLogger("nexus2")
            nexus_logger.info(f"Nexus Dispatch: '{user_input[:30]}...' → {result.get('agents')} (conf: {result.get('confidence')})")
            
            return result
            
        except Exception as e:
            print(f"Nexus Dispatch Error: {e}")
            # フォールバック：全エージェント
            return {
                "intent": "解析失敗",
                "agents": ["Strategist", "Director", "Analyst"],
                "confidence": 0.5,
                "rationale": "意図解析に失敗したため、全エージェントにアサイン"
            }

    def route_to_agents(self, user_input: str, history: list = None) -> dict:
        """
        Nexus 2.0 統合ルーティング
        意図解析→エージェント選択→各エージェントからの応答収集
        """
        # 1. 意図解析
        dispatch_result = self.semantic_dispatch(user_input)
        agents = dispatch_result.get("agents", [])
        
        responses = {}
        
        # 2. 各エージェントからの応答を収集
        for agent in agents:
            if agent == "Strategist":
                responses["Strategist"] = self.consult(history or [], user_input)
            elif agent == "Director":
                responses["Director"] = self.chat_session(history or [], user_input)
            elif agent == "Analyst":
                # Analystはデータ分析に特化した応答を生成（簡易実装）
                responses["Analyst"] = self._get_analyst_response(user_input)
        
        return {
            "dispatch": dispatch_result,
            "responses": responses
        }

    def _get_analyst_response(self, user_input: str) -> str:
        """Analyst（分析官）の応答生成"""
        try:
            prompt = f"""
あなたは「Analyst（分析官）」です。データと事実に基づいた冷徹な分析を行います。

## ユーザーの質問/要望
{user_input}

## 役割
- 感情論を排し、客観的データに基づいて回答
- 数値やメトリクスを可能な限り引用
- 弱点や改善点を遠慮なく指摘

簡潔かつ具体的に分析結果を述べてください。
"""
            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.3)
            )
            return response.text
        except Exception as e:
            return f"分析エラー: {e}"

    def _build_consultant_persona(self, constitution: dict, user_model: dict) -> str:
        """戦略コンサルタントモードのペルソナ指示書を構築"""
        channel_name = constitution.get('channel_name', 'Channel')
        biz_rank = user_model.get('ranks', {}).get('biz_rank', {}).get('level', 'Novice')
        biz_advice = (
            "初心者なので、専門用語を避け、具体的で簡単なアクションアイテム（Do This）を提示してください。"
            if biz_rank == 'Novice' else
            "プロ同士として、高度なマーケティング理論を用いた議論を行ってください。"
        )
        return self.persona_consultant.format(
            channel_name=channel_name,
            biz_rank=biz_rank,
            biz_advice_mode=biz_advice
        )

    def _build_director_persona(self, user_model: dict) -> str:
        """映像監督モードのペルソナ指示書を構築"""
        tech_rank = user_model.get('ranks', {}).get('tech_rank', {}).get('level', 'Novice')
        tech_advice = (
            "初心者なので、ツールの使い方は手取り足取り教え、複雑な演出は代わりにやってあげてください。"
            if tech_rank == 'Novice' else
            "上級者なので、抽象的なイメージ共有だけで意図を汲み取り、より洗練された演出を提案してください。"
        )
        return self.persona_director.format(
            tech_rank=tech_rank,
            tech_advice_mode=tech_advice
        )

    def _get_system_instruction(self, mode="consult"):
        """
        アクティブな脳（モード）に基づいてシステム指示書を動的に構築します。
        """
        branding_mgr = branding_manager
        constitution = branding_mgr.constitution
        user_model = branding_mgr.user_model

        # Select Persona base
        if mode == "consult":
            base_persona = self._build_consultant_persona(constitution, user_model)
        else:
            base_persona = self._build_director_persona(user_model)

        # Resolve Auto-Pilot Ratio
        auto_pilot_ratio = user_model.get('automation_settings', {}).get('auto_pilot_ratio', 0.9)
        auto_pilot_percent = int(auto_pilot_ratio * 100)
        
        automation_directive = f"""
        ## 🤖 AUTO-PILOT LEVEL: {auto_pilot_percent}%
        現在の自動化率は「{auto_pilot_percent}%」です。
        - {auto_pilot_percent}% の意思決定をあなたが自律的に行ってください。
        - 残りの {100 - auto_pilot_percent}% については、ユーザーに確認や承認を求めてください。
        """

        # Inject Common Context (The Vault Knowledge)
        context = branding_mgr.get_context_block()
        
        # Phase 26: Inject Deep Context (Subtitles & Vision)
        deep_context = branding_mgr.get_deep_context()
        
        full_instruction = f"""
        {base_persona}

        {automation_directive}

        =========================================
        ## 共通コンテキスト情報 (The Trinity Data)
        {context}
        =========================================

        =========================================
        ## 動画固有の深層文脈 (The Deep Soul)
        {deep_context}
        =========================================
        
        ## 行動指針
        - あなたは「一つの生命体」の一部です。必要であれば、もう一方の人格（{ '右脳' if mode == 'consult' else '左脳' }）の意見も参照するよう言及してください。
        - **重要**: 提供された字幕内容（DEEP CONTEXT）を熟読し、動画の内容と矛盾しない提案を行ってください。
        """
        
        logger.info(f"Generated System Instruction (len: {len(full_instruction)}). Deep Context preview: {deep_context[:100]}...")
        
        return full_instruction

    def consult(self, history, user_input):
        """
        Left Brain Session (Strategy Meeting)
        """
        try:
            sys_inst = self._get_system_instruction(mode="consult")
            chat = self.client.chats.create(
                model=self.chat_model,
                config=types.GenerateContentConfig(system_instruction=sys_inst, temperature=0.5), # Logical = Low Temp
                history=history
            )
            response = chat.send_message(user_input)
            return response.text
        except Exception as e:
            print(f"Consult Error: {e}")
            return f"Strategic Context Error: {e}"

    def chat_session(self, history, user_input):
        """
        Right Brain Session (Creative Direction)
        """
        try:
            sys_inst = self._get_system_instruction(mode="director")
            chat = self.client.chats.create(
                model=self.chat_model,
                config=types.GenerateContentConfig(system_instruction=sys_inst, temperature=0.8), # Creative = High Temp
                history=history
            )
            response = chat.send_message(user_input)
            return response.text
        except Exception as e:
            print(f"Director Error: {e}")
            return f"Creative Context Error: {e}"

    def generate_image(self, prompt, aspect_ratio="16:9"):
        """
        Generates images. 
        Injects Brand Style Prompt automatically.
        """
        try:
            # Inject Brand Visual Identity
            style = branding_manager.constitution.get('visual_identity', {}).get('style_prompt', '')
            enhanced_prompt = f"{style}, {prompt}"
            
            print(f"Generating with Style: {enhanced_prompt}") # Debug Log
            
            response = self.client.models.generate_images(
                model=self.image_model,
                prompt=enhanced_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=4,
                    aspect_ratio=aspect_ratio,
                    include_rai_reason=True,
                    output_mime_type="image/jpeg"
                )
            )
            
            images_b64 = []
            for generated_image in response.generated_images:
                images_b64.append(generated_image.image.image_bytes)
                
            return images_b64
            
        except Exception as e:
            print(f"Image Gen Error Detail: {e}")
            import traceback
            traceback.print_exc()
            return []

    # ... process_image_task remains same ...
    def process_image_task(self, task_id, prompt):
        task_manager.update_task(task_id, "processing")
        try:
            images_bytes = self.generate_image(prompt)
            if not images_bytes:
                task_manager.update_task(task_id, "failed", error="No images generated")
                return
            images_b64_str = [base64.b64encode(img).decode('utf-8') for img in images_bytes]
            task_manager.update_task(task_id, "completed", result=images_b64_str)
        except Exception as e:
            print(f"Task {task_id} Failed: {e}")
            task_manager.update_task(task_id, "failed", error=str(e))

    def analyze_script(self, full_text):
        """
        Analyzes the full script and proposes 3 visual style concepts.
        Output is strictly JSON.
        """
        try:
            prompt = f"""
            You are an expert Art Director. Analyze the following video script and propose 3 distinct visual style concepts.
            
            ## Script Content
            {full_text[:5000]}... (truncated if too long)
            
            ## Output Format (JSON Only)
            Provide a list of 3 objects, each with:
            - "id": "style_a" (or b, c)
            - "name": Short catchy title (e.g., "Neon Cyberpunk")
            - "description": Explanation of why this fits (Japanese)
            - "visual_prompt": The actual prompt to be used for image generation (English)
            """

            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            return response.text
        except Exception as e:
            print(f"Analysis Error: {e}")
            # Fallback JSON if AI fails
            return json.dumps([
                {"id": "style_a", "name": "Standard Professional", "description": "信頼感のある標準的なスタイル", "visual_prompt": "Professional studio lighting, 4k, clean background, trustworthy atmosphere"},
                {"id": "style_b", "name": "Warm & Friendly", "description": "親しみやすい暖色系のスタイル", "visual_prompt": "Warm lighting, cozy atmosphere, soft focus, welcoming vibe"},
                {"id": "style_c", "name": "Tech & Futuristic", "description": "先進性を感じる寒色系のスタイル", "visual_prompt": "Cyberpunk, neon lights, high contrast, futuristic tech background"}
            ])

    def generate_storyboard_plan(self, full_text, scenes, selected_style):
        """
        Generates a detailed storyboard plan (AI vs Real Asset) with Director's Notes.
        """
        try:
            # Prepare scene summaries
            scene_context = ""
            for i, s in enumerate(scenes):
                scene_context += f"Scene {i}: {s.get('name')} - {s.get('description')}\n"

            prompt = f"""
            You are the Art Director. Based on the selected style "{selected_style['name']}" ({selected_style['visual_prompt']}),
            create a detailed storyboard plan for the following scenes.
            
            ## Selected Style
            {selected_style['name']}: {selected_style['description']}

            ## Scenes
            {scene_context}

            ## Task
            For EACH scene, decide the best visual source:
            1. **AI Generation**: If the scene is abstract, emotional, or generic.
            2. **Real Asset**: If the scene mentions a specific person (Guest), product name (e.g. Uniqlo), or requires evidentiary footage/photo.

            ## Output Format (JSON Only)
            Return a list of objects (one for each scene in order):
            - "index": integer (0, 1, 2...)
            - "source_type": "AI" or "USER_ASSET"
            - "rationale": (Japanese) Explanation of your intent. Why this visual? Why this source?
                - If AI: Explain the lighting, mood, and composition intent.
                - If Asset: Explain WHAT specific asset is needed (e.g., "Guest's profile photo", "Uniqlo product shot").
            - "visual_prompt": (English) Refined prompt for AI generation (only if source_type is AI, otherwise null).
            - "asset_suggestion": (Japanese) Suggestion of what asset to look for (only if source_type is USER_ASSET, otherwise null).
            """

            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.5
                )
            )
            return response.text
        except Exception as e:
            print(f"Storyboard Plan Error: {e}")
            # Fallback
            result = []
            safe_scenes = scenes if hasattr(scenes, '__iter__') else []
            for i, s in enumerate(safe_scenes):
                name = ""
                if isinstance(s, dict):
                    name = s.get('name', f"Scene {i}")
                elif s is not None:
                    name = getattr(s, 'name', f"Scene {i}")
                else:
                    name = f"Scene {i}"
                result.append({
                    "index": i,
                    "source_type": "AI",
                    "rationale": "AIによる標準的な生成を行います。",
                    "visual_prompt": f"Scene context: {name}",
                    "asset_suggestion": None
                })
            return json.dumps(result)

    def analyze_resource_needs(self, full_text):
        """
        Scans the script for potential asset needs (Material Audit).
        Returns a list of identified needs.
        """
        try:
            prompt = f"""
            You are a Production Manager. Analyze the video script and identify specific assets (photos, videos, logos) that are likely needed.
            Focus on proper nouns, product names, specific people, or locations that cannot be generic.
            
            ## Script
            {full_text[:5000]}
            
            ## Output Format (JSON List)
            Return a list of objects:
            - "id": "asset_1"
            - "name": Brief intent (e.g., "Uniqlo Fleece Photo", "Store Exterior")
            - "category": "Product" | "Person" | "Location" | "Logo" | "Other"
            - "reason": Why is this needed? (e.g., "Product name is mentioned explicitly")
            """
            
            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )
            return response.text
        except Exception as e:
            print(f"Resource Audit Error: {e}")
            return json.dumps([])

    def calculate_quality_score(self, storyboard_plan, biz_rank="Novice"):
        """
        Calculates a 'Production Quality Score' based on the plan and user level.
        """
        try:
            # Convert plan to string context
            plan_str = str(storyboard_plan)
            
            prompt = f"""
            You are a Quality Assurance Director. Evaluate the following Storyboard Plan.
            
            ## User Level
            {biz_rank} (Expectations: {"High" if biz_rank != 'Novice' else "Basic"})
            
            ## Storyboard Plan (Scenes & Sources)
            {plan_str}
            
            ## Scoring Criteria
            1. **Asset Utilization**: are real assets used for products/people? (Crucial for high score)
            2. **Visual Variety**: Is it all generic AI?
            3. **Intent**: Are the rationales clear?
            
            ## Output Format (JSON)
            - "score": integer (0-100)
            - "rank": "S" | "A" | "B" | "C" | "D"
            - "comment": Short feedback (Japanese). Explain why.
            - "advice": Actionable logic to improve score (Japanese).
            - "is_acceptable": boolean (Is it ready to publish based on standards?)
            """
            
            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.4
                )
            )
            return response.text
        except Exception as e:
            print(f"Scoring Error: {e}")
            # **採点が落ちたときに「合格」を返さない**（R1.5-C4）。
            # ここは以前 `score: 50 / is_acceptable: True` を返していた。
            # UI（`frontend/src/components/DirectorBriefing.jsx:531,552,554`）は
            # `is_acceptable` で緑の「制作開始 (Go)」を出すので、
            # **API が落ちていても「品質チェックに通った」と見えていた。**
            # 点を出せないときは点を名乗らない（`score: None`）。
            return json.dumps({
                "score": None,
                "rank": None,
                "comment": f"スコア計算に失敗しました（{type(e).__name__}）。**採点は行われていません。**",
                "advice": "API キーと通信状態を確認して、もう一度採点してください。",
                "is_acceptable": False,
                "is_real": False,
                "data_source": "unavailable",
                "error": str(e),
            })

    def process_batch_image_task(self, task_id, scenes, style_prompt):
        """
        Batch processes image generation for multiple scenes.
        Updates task status with progress.
        """
        task_manager.update_task(task_id, "processing", result={"progress": 0, "images": {}})
        
        generated_results = {} # { index: base64_str }
        total = len(scenes)
        
        try:
            for i, scene in enumerate(scenes):
                # Construct Prompt
                scene_desc = scene.get('description', '')
                scene_name = scene.get('name', '')
                full_prompt = f"{style_prompt}, Scene Context: {scene_name} - {scene_desc}"
                
                print(f"Batch Gen [{i+1}/{total}]: {full_prompt}")
                
                # Generate (Synchronous call to existing method)
                # We request 1 high quality image for batch to save time/cost, or 4? 
                # Let's do standard generation which returns 4, but we pick the first one for the timeline?
                # Or maybe we change generate_image config? For now use existing.
                images_bytes = self.generate_image(full_prompt)
                
                if images_bytes:
                    # Take the first image as the default "Apply" choice
                    # But we might want to store all 4? For now, let's store the first one to keep payload small?
                    # No, user wants choice. But for batch, maybe just 1 is enough for speed?
                    # Let's store all 4 but in a compressed way or just list.
                    # Actually, SceneTimeline expects `image` string (url/base64).
                    # Let's save the first one as "selected" candidate.
                    
                    img_b64 = base64.b64encode(images_bytes[0]).decode('utf-8')
                    generated_results[str(i)] = img_b64
                
                # Update Progress
                progress = int((i + 1) / total * 100)
                task_manager.update_task(task_id, "processing", result={
                    "progress": progress, 
                    "images": generated_results,
                    "current_scene": i
                })
                
                # Sleep briefly to avoid rate limits if necessary
                time.sleep(1)

            task_manager.update_task(task_id, "completed", result=generated_results)

        except Exception as e:
            print(f"Batch Task Failed: {e}")
            task_manager.update_task(task_id, "failed", error=str(e))

    def generate_production_report(self, storyboard_plan, quality_score, biz_rank="Novice"):
        """
        Analyzes the session results and generates a 'Production Post-Mortem' report.
        Suggests agenda items for the Strategy Council.
        """
        try:
            # Convert context to string
            plan_str = str(storyboard_plan)
            score_str = str(quality_score)
            
            prompt = f"""
            You are the Production Manager creating a Post-Mortem Report.
            Analyze the relationship between the PLAN and the RESULT (Score).
            
            ## Context
            - User Level: {biz_rank}
            - Storyboard Plan: {plan_str}
            - Final Quality Score: {score_str}
            
            ## Task
            Identify 1 significant insight or "Motion for Amendment" to the Brand Constitution.
            (e.g., "User consistently prefers Realism over Abstract. Change 'Style' rule?")
            
            ## Output Format (JSON)
            - "summary": (Japanese) Brief summary of the session.
            - "success_factor": (Japanese) What went well?
            - "issue_detected": (Japanese) What needs improvement?
            - "agenda_proposal": (Japanese) A specific question to ask the Boardroom Council.
              (e.g., "The user struggled with AI prompts. Should we increase automation to 100%?")
            - "xp_grant": integer (suggested XP, usually 50-100)
            """
            
            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.4
                )
            )
            return response.text
        except Exception as e:
            print(f"Report Error: {e}")
            return json.dumps({
                "summary": "セッション完了",
                "success_factor": "完了したこと",
                "issue_detected": "特になし",
                "xp_grant": 50
            })

    def verify_production_quality(self, full_text, scenes, segments):
        """
        [NEW] Phase 18: Quality Gate Agent
        Performs a final multi-perspective check before rendering.
        """
        try:
            prompt = f"""
            あなたは「最終品質管理責任者 (QA Director)」です。
            映像の書き出し（レンダリング）を行う前に、構成と字幕の最終チェックを行います。

            ## 脚本 (Script)
            {full_text[:3000]}

            ## シーン構成 (Scenes)
            {json.dumps([{ "name": s.get('name'), "asset": s.get('source_type') } for s in scenes], ensure_ascii=False)}

            ## 字幕データ (Segments)
            {json.dumps([s.get('text') for s in segments[:50]], ensure_ascii=False)} ... (先頭50行)

            ## チェック項目 (Quality Gate)
            1. **言語の整合性**: 字幕に明らかな誤字、不自然な日本語、放送禁止用語がないか。
            2. **演出の論理性**: 脚本の意図とシーンのビジュアル（AI生成か実写か）が矛盾していないか。
            3. **ブランド保護**: 憲法に示されたトーン＆マナーから逸脱していないか。
            4. **リズム**: 視聴者が読みきれないほど長い字幕や、極端に短い字幕が放置されていないか。

            ## 出力形式 (JSON Only)
            {{
                "is_ready": boolean,
                "score": integer,
                "critical_issues": ["項目1", "項目2"],
                "suggestions": ["提案1", "提案2"],
                "final_verdict": "日本語による最終的な承認・却下メッセージ"
            }}
            """
            
            response = self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2 
                )
            )
            return response.text
        except Exception as e:
            print(f"Quality Gate Error: {e}")
            # **検査が落ちたら「進行可能」と言わない**（R1.5-C4）。
            # ここは `is_ready: True / score: 80` を返していたので、
            # **QA エンジンが一度も走っていなくてもレンダリングへ進めた。**
            # `calculate_quality_score()` の except を直したのと同じ扱い。
            return json.dumps({
                "is_ready": False,
                "score": None,
                "critical_issues": [],
                "suggestions": ["通信とAPIキーを確認して、もう一度検査してください。"],
                "final_verdict": f"QAエンジンエラーのため、検査は行われていません（{type(e).__name__}）。"
                                 "手動確認を推奨します。",
                "is_real": False,
                "data_source": "unavailable",
                "error": str(e),
            })

# Instantiate the Brain
brain = DirectorBrain()
