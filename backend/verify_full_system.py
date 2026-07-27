import requests
import json
import os
import sys
import time

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
DEFAULT_FRONTEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
FRONTEND_PATH = os.environ.get("FRONTEND_PATH", DEFAULT_FRONTEND_PATH)

def log_success(msg):
    print(f"✅ PASS: {msg}")

def log_failure(msg):
    print(f"❌ FAIL: {msg}")
    sys.exit(1)

def _fetch_backend_status():
    """Send HTTP GET request to backend status API."""
    try:
        return requests.get(f"{API_BASE}/api/status", timeout=10)
    except requests.exceptions.RequestException as e:
        log_failure(f"Could not connect to backend: Connection error: {e}")

def _parse_and_validate_status_response(res):
    """Parse status response and validate JSON schema."""
    if res is None:
        log_failure("Could not connect to backend: Response is None")
        return None
    if res.status_code != 200:
        log_failure(f"Backend returned status code {res.status_code}")
        return None

    try:
        data = res.json()
        if not isinstance(data, dict):
            log_failure(f"Backend returned non-dict status response: {type(data).__name__}")
        return data
    except (json.JSONDecodeError, ValueError) as e:
        log_failure(f"Could not connect to backend: Invalid JSON response: {e}")

def check_backend_health():
    print("\n--- 1. Backend Health Check ---")
    res = _fetch_backend_status()
    data = _parse_and_validate_status_response(res)
    log_success(f"Backend is online. Status: {data.get('status')} - {data.get('message')}")
    return data

def _fetch_council_session(query):
    """Send HTTP POST request to Council API to create a debate session."""
    try:
        return requests.post(f"{API_BASE}/api/council/session", params={"query": query}, timeout=10)
    except requests.exceptions.RequestException as e:
        log_failure(f"Council API Error: Network or timeout error: {e}")

def _validate_council_response_data(res):
    """Parse and validate Council session response."""
    if res is None:
        log_failure("Council API Error: Response is None")
        return None, None, None
    if res.status_code != 200:
        log_failure(f"Council API returned {res.status_code}: {res.text}")
        return None, None, None

    try:
        data = res.json()
    except (json.JSONDecodeError, ValueError) as e:
        log_failure(f"Council API Error: Invalid JSON response: {e}")

    if not isinstance(data, dict):
        log_failure(f"Council API returned non-dict response: {type(data).__name__}")

    session_id = data.get('session_id')
    debate_flow = data.get('debate_flow')
    synthesis = data.get('synthesis')

    if not session_id:
        log_failure("No session_id returned.")
    if not debate_flow or len(debate_flow) == 0:
        log_failure("No debate_flow returned (Agents are silent).")
    if not synthesis:
        log_failure("No synthesis returned (Nexus failed).")
    
    if not isinstance(synthesis, dict):
        log_failure(f"Council API Error: synthesis is not a dict: {type(synthesis).__name__}")
        
    proposal = synthesis.get('proposal')
    if proposal is None:
        log_failure("Council API Error: synthesis is missing proposal key.")
        return session_id, debate_flow, None
        
    if not isinstance(proposal, str):
        log_failure(f"Council API Error: proposal is not a string: {type(proposal).__name__}")
        return session_id, debate_flow, None
        
    return session_id, debate_flow, proposal

def check_council_api():
    print("\n--- 2. Council of Minds API Check (Constitutional Art. 7) ---")
    query = "E2E Test: How to improve system stability?"
    print(f" sending query: '{query}'...")
    
    res = _fetch_council_session(query)
    session_id, debate_flow, proposal = _validate_council_response_data(res)
        
    log_success(f"Council Session {session_id} successful.")
    log_success(f"Agents responded: {len(debate_flow)} items.")
    log_success(f"Synthesis Proposal: {proposal[:50]}...")
    return session_id

def _verify_required_files_exist(frontend_path, file_list):
    """Verify that all required files exist under the frontend path."""
    for relative_path in file_list:
        full_path = os.path.join(frontend_path, relative_path)
        if os.path.exists(full_path):
            log_success(f"Found {relative_path}")
        else:
            log_failure(f"Missing critical frontend file: {relative_path}")

def _verify_css_styles(frontend_path):
    """Read App.css and verify font and theme configuration."""
    css_path = os.path.join(frontend_path, "src", "App.css")
    try:
        with open(css_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        log_failure(f"Could not read App.css: {e}")
        return

    if "Noto Sans JP" in content:
        log_success("App.css contains 'Noto Sans JP' (Localization Verified)")
    else:
        log_failure("App.css missing 'Noto Sans JP' font definition.")
    
    if "--bg-primary: #f5f5f7" in content or "background-color: var(--bg-primary)" in content:
        log_success("App.css contains Light Theme variables.")
    else:
        log_failure("App.css missing Light Theme variables.")

def check_frontend_integrity():
    print("\n--- 3. Frontend Integrity Check (Static) ---")
    
    required_files = [
        "src/App.jsx",
        "src/App.css",
        "src/components/Boardroom.jsx",
        "src/components/CouncilChamber.jsx",
        "index.html"
    ]
    _verify_required_files_exist(frontend_path=FRONTEND_PATH, file_list=required_files)
    _verify_css_styles(frontend_path=FRONTEND_PATH)

def main():
    print("🚀 Starting Mirai Gikai E2E Verification...")
    
    check_backend_health()
    check_council_api()
    check_frontend_integrity()
    
    print("\n✨ ALL SYSTEMS GO. STARTING UI TEST VIA BROWSER AGENT...")

if __name__ == '__main__':
    main()
