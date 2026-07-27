import sys
import os
import uuid
import asyncio
from dotenv import load_dotenv

# Load API Key
load_dotenv()

# Add backend to path to allow imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.council_graph import run_council
from agents.council_logger import council_logger

def run_council_simulation():
    print("--- 🏛️ THE COUNCIL OF MINDS: SIMULATION START ---")
    
    # 0. Setup
    simulation_topic = "Why is my channel growing so slowly?"
    session_id = str(uuid.uuid4())
    
    print(f"\n🗣️ User Query: '{simulation_topic}'")
    
    # 1. Run Council (Async to Sync)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            run_council(
                user_query=simulation_topic,
                council_mode="post_production",
                session_id=session_id
            )
        )
    finally:
        loop.close()
        
    synthesis = result.get("synthesis", "")
    print(f"\n⚖️ Nexus Synthesis: \"{synthesis}\"")
    
    # 2. Logging
    synthesis_dict = {"proposal": synthesis}
    log_path = council_logger.log_session(
        session_id=session_id,
        topic=simulation_topic,
        debate_data=[],
        synthesis=synthesis_dict
    )
    
    if log_path:
        print("\n✅ Simulation Complete. Log verified.")
    else:
        print("\n❌ Simulation Failed to log.")

if __name__ == "__main__":
    run_council_simulation()
