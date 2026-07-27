"""ADK + Gemini API 接続テスト"""
import asyncio
import os
import dotenv
import pytest

dotenv.load_dotenv()

@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"),
    reason="GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set"
)
async def test_adk_gemini():
    from google.adk.agents import Agent
    from google.adk.runners import InMemoryRunner
    from google.adk.agents.run_config import RunConfig
    from google.genai import types as gt

    print("--- ADK + Gemini 2.5 Flash Test ---")
    
    agent = Agent(
        name="test_agent",
        model="gemini-2.5-flash",
        instruction="あなたは日本語で挨拶するアシスタントです。短く返答してください。",
    )
    
    runner = InMemoryRunner(agent=agent, app_name="test")
    session = await runner.session_service.create_session(
        app_name="test", user_id="u1",
    )
    
    content = gt.Content(
        role="user",
        parts=[gt.Part(text="こんにちは")],
    )
    
    run_config = RunConfig(max_llm_calls=3)
    
    print(f"Session: {session.id}")
    print(f"Model: gemini-2.5-flash")
    print(f"Sending: 'こんにちは'")
    print()
    
    response_text = ""
    async for event in runner.run_async(
        user_id="u1",
        session_id=session.id,
        new_message=content,
        run_config=run_config,
    ):
        author = getattr(event, "author", "?")
        is_final = event.is_final_response()
        
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"  [{author}] {part.text[:200]}")
                    if is_final:
                        response_text += part.text
    
    print()
    if response_text:
        print(f"✅ ADK + Gemini OK: '{response_text[:100]}'")
    else:
        print("❌ No response received")


if __name__ == "__main__":
    asyncio.run(test_adk_gemini())
