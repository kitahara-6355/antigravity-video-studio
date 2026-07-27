from abc import ABC, abstractmethod
import os
import time
import json
from google.genai import types
from gemini_client_factory import get_gemini_client
import logging

logger = logging.getLogger(__name__)

# Import ADK elements and check for availability
try:
    from google.adk.agents import Agent as ADKAgent
    from google.adk.runners import InMemoryRunner
    HAS_ADK = True
except ImportError:
    HAS_ADK = False

# Import Model Registry
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-2.5-flash"

class DummyModels:
    def generate_content(self, *args, **kwargs):
        raise RuntimeError("Gemini Client is not initialized (API Key missing)")

class DummyClient:
    def __init__(self):
        self.models = DummyModels()

class Agent(ABC):
    """
    Abstract Base Class for all Council Agents.
    Enforces a standard interface for input/output and history logging.
    """
    def __init__(self, name, role, color=None):
        self.name = name
        self.role = role
        self.color = color or "#cccccc" # UI Color for Mirai Gikai
        # Initialize LLM Client via Factory
        self.client = get_gemini_client() or DummyClient()
        self.types = types
        # Use Model Registry for centralized model management
        try:
            self.model_name = get_model("supervisor")
        except Exception as e:
            logger.warning(f"Failed to load model from registry in base class, falling back to default: {e}")
            self.model_name = "gemini-2.5-flash"

        
        # Soul File Setup
        self.memory_dir = os.path.dirname(os.path.abspath(__file__)) + "/memory"
        os.makedirs(self.memory_dir, exist_ok=True)
        self.soul_path = os.path.join(self.memory_dir, f"{name}.json")
        self.soul = self._load_soul()

    def _load_soul(self):
        """Loads the agent's persistent memory (Soul)."""
        if os.path.exists(self.soul_path):
            try:
                with open(self.soul_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: JSON decode error in soul file for {self.name}: {e}")
            except OSError as e:
                print(f"Warning: OS error reading soul file for {self.name}: {e}")
            except (TypeError, ValueError) as e:
                print(f"Warning: Unexpected error loading soul for {self.name}: {e}")
        return {
            "stats": {"debates": 0, "wins": 0, "losses": 0},
            "bias_weight": 1.0, # 1.0 = Normal, >1.0 = Confident
            "history": []
        }

    def _save_soul(self):
        """Saves the agent's soul to disk."""
        try:
            with open(self.soul_path, 'w', encoding='utf-8') as f:
                json.dump(self.soul, f, indent=2, ensure_ascii=False)
        except (TypeError, OSError) as e:
            print(f"Error saving soul for {self.name}: {e}")
        except ValueError as e:
            print(f"Unexpected error saving soul for {self.name}: {e}")

    def learn(self, session_id, my_stance, final_outcome, feedback_text=None):
        """
        Adapts based on the Chairman decision.
        If REJECTED, it tries to extract a 'Lesson' to avoid repeating the mistake.
        """
        timestamp = time.time()
        
        # 1. Update Stats
        self.soul['stats']['debates'] += 1
        if final_outcome == "APPROVE" and my_stance == "AGREE":
             self.soul['stats']['wins'] += 1
        elif final_outcome == "REJECT" and my_stance == "AGREE":
             self.soul['stats']['losses'] += 1
             
        # 2. Record History
        memory = {
            "session_id": session_id,
            "timestamp": timestamp,
            "stance": my_stance,
            "outcome": final_outcome,
            "feedback": feedback_text
        }
        self.soul['history'].append(memory)
        
        # 3. Extract Lesson (If Rejected)
        if final_outcome == "REJECT" and my_stance == "AGREE":
            # In a real system, we'd use LLM to summarize WHY it was rejected.
            # For now, if explicit feedback is provided, store it as a lesson.
            if feedback_text:
                lesson = f"Avoid proposal that caused: {feedback_text}"
                print(f"💡 {self.name} Learned Lesson: {lesson}")
                
                # Embeddingの生成
                from agents.vector_utils import get_embedding
                emb = get_embedding(self.client, lesson)
                
                self.soul.setdefault('lessons', []).append({
                    "text": lesson,
                    "created_at": timestamp,
                    "weight": 1.0,
                    "embedding": emb
                })
                # Decrease confidence slightly
                self.soul['bias_weight'] = max(0.8, self.soul['bias_weight'] - 0.1)

        # 4. Save
        self._save_soul()

    def recall(self, query, top_k=3):
        """
        現在のクエリに関連するレッスン（教訓）をベクトル類似度に基づいて取得する。
        常に固定ルールの蒸留済みルール (distilled_rules) をマージして返す。
        """
        distilled_rules = self.soul.get('distilled_rules', [])
        lessons = self.soul.get('lessons', [])
        
        if not lessons or not query:
            return distilled_rules
            
        from agents.vector_utils import get_embedding, cosine_similarity
        query_emb = get_embedding(self.client, query)
        
        if not query_emb:
            # Embedding取得失敗時は直近のレッスンをフォールバックとして返す
            fallback_lessons = [l['text'] for l in lessons[-top_k:]]
            return distilled_rules + fallback_lessons
            
        scored_lessons = []
        needs_save = False
        
        for l in lessons:
            emb = l.get('embedding')
            # 過去のデータや未生成のデータに対してオンデマンドで生成して埋める
            if not emb:
                emb = get_embedding(self.client, l['text'])
                l['embedding'] = emb
                needs_save = True
                
            similarity = cosine_similarity(query_emb, emb) if emb else 0.0
            scored_lessons.append((similarity, l['text']))
            
        if needs_save:
            self._save_soul()
            
        # 類似度の高い順にソートし、上位 top_k 件を抽出
        scored_lessons.sort(key=lambda x: x[0], reverse=True)
        retrieved_lessons = [text for sim, text in scored_lessons[:top_k] if sim > 0.1]
        
        return distilled_rules + retrieved_lessons

    @abstractmethod
    def process(self, input_data: dict, context: dict, council_context=None) -> dict:
        """
        Process the input and return a structured response.
        council_context: instance of CouncilContext if available.
        """
        pass
        
    def _inject_council_findings(self, council_context):
        """Helper to inject findings from other agents into the prompt."""
        if not council_context:
            return ""
        
        if isinstance(council_context, dict):
            findings = council_context
        elif hasattr(council_context, 'get_findings'):
            findings = council_context.get_findings()
        else:
            findings = {}
        if not findings:
            return ""
            
        context_block = "\n## 🏛️ 専門家メンバーからの知見 (Collaboration Context)\n"
        for agent, text in findings.items():
            if agent != self.name: # Don't inject own findings
                context_block += f"- **{agent}**: {text}\n"
        return context_block

    def _create_base_response(self):
        return {
            "agent": self.name,
            "role": self.role,
            "color": self.color,
            "timestamp": time.time(),
            "stance": "NEUTRAL",
            "summary": "No opinion",
            "detail": ""
        }

    def notify_thinking(self, context):
        """WebSocketを通じてエージェントが思考中であることを通知"""
        try:
            import asyncio
            from websocket_handler import broadcaster
            sid = context.get("session_id", "default") if context else "default"
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                loop.create_task(broadcaster.update_council_state(sid, self.name, "thinking"))
        except (ImportError, AttributeError, RuntimeError, TypeError) as e:
            # バックグラウンド配信のエラーがメインの処理フローを阻害しないよう優雅にフォールバック
            logger.debug(f"WS notification failed (thinking): {e}")

    def notify_done(self, context, result):
        """WebSocketを通じてエージェントが思考完了したことを通知"""
        try:
            import asyncio
            from websocket_handler import broadcaster
            sid = context.get("session_id", "default") if context else "default"
            stance = result.get("stance", "NEUTRAL")
            summary = result.get("summary", "")
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                loop.create_task(broadcaster.update_council_state(sid, self.name, "done", stance, summary))
        except (ImportError, AttributeError, RuntimeError, TypeError) as e:
            logger.debug(f"WS notification failed (done): {e}")
