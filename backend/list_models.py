"""
List available Gemini models using google-genai SDK.
Security fix: API key loaded from .env file.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError

logger = logging.getLogger(__name__)

# Load API key from .env
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

def list_gemini_models() -> list[str]:
    """Lists available Gemini models."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found in .env")
        return []
    
    from gemini_client_factory import get_gemini_client
    client = get_gemini_client()
    if not client:
        print("Error: Failed to get Gemini client.")
        return []
    
    model_list = []
    try:
        models = client.models.list()
        if models:
            for m in models:
                if hasattr(m, 'name') and m.name:
                    model_list.append(m.name)
        return model_list
    except APIError as e:
        logger.exception("Google GenAI API error while listing models: %s", e)
        return []

if __name__ == "__main__":
    print("--- Available Models ---")
    models = list_gemini_models()
    for m in models:
        print(f"Model: {m}")
