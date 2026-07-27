import sys
import os
import time
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.director import Director

def test_learning_loop():
    print("--- 🧠 INFINITE EVOLUTION TEST ---")
    
    director = Director()
    print(f"Agent: {director.name}")
    print(f"Memory Path: {director.soul_path}")
    
    # 1. Simulate a Proposal
    session_id = f"test_{int(time.time())}"
    print(f"\n[Session 1] Query: 'How to edit this interview?'")
    
    # Fake response for simulation (Pre-learning)
    # In real life, we'd call process(), but we want to force a learning event.
    print("Director Proposal: 'Use lots of Jump Cuts for energy.'")
    
    # 2. User Rejects with Feedback
    feedback = "I hate jump cuts. Never use them."
    print(f"User Action: REJECT (Feedback: '{feedback}')")
    
    director.learn(session_id, "AGREE", "REJECT", feedback_text=feedback)
    
    # 3. Verify Memory Update
    print("\n... Sleeping to allow memory save ...")
    time.sleep(1)
    
    # Reload from disk to prove persistence
    new_director = Director()
    lessons = new_director.recall("jump cuts")
    print(f"Recall Check: {lessons}")
    
    if any("hate jump cuts" in l for l in lessons):
        print("✅ SUCCESS: The Agent remembered the lesson.")
    else:
        print("❌ FAILURE: Lesson not found in memory.")
        
    # 4. Verify Context Injection (Dry Run)
    print("\n[Session 2] Query: 'Editing advice?'")
    # We call process() to see if the lesson appears in the system prompt logs (if we had them)
    # Or simply trust the logic we implemented.
    # Let's actually run a real query to see if the LLM mentions the constraint.
    
    res = new_director.process({"text": "How should I cut the video?"}, {})
    print(f"Director New Proposal: {res.get('detail', 'No detail')}")

if __name__ == "__main__" or os.environ.get("TEST_VERIFY_LEARNING_MAIN") == "1":
    test_learning_loop()

