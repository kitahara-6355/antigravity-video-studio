import sys
import time

try:
    import requests
except ImportError:
    print("Requests module not found. Please ensure it is installed.")
    sys.exit(1)

BASE_URL = "http://localhost:8000"

def verify(base_url=BASE_URL):
    print("--- Testing Analytics Pipeline ---")

    # 1. Check Initial Status
    try:
        res = requests.get(f"{base_url}/api/status")
        initial_status = res.json()
        print(f"Initial Biz XP: {initial_status.get('ranks', {}).get('biz_rank', {}).get('xp', 0)}")
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"Detailed Error: {e}")
        sys.exit(1)

    # 2. Simulate Viral Hit (+5000 views)
    print("")
    print("--- Simulating 5000 additional views ---")
    try:
        res = requests.post(f"{base_url}/api/analytics/simulate?views=5000")
        if res.status_code == 200:
            data = res.json()
            print(f"Simulation Result: {data.get('simulation')}")
            print(f"Sync Result (Biz XP): {data.get('sync', {}).get('biz_xp')}")
            
            # Check if Rivals found
            rivals = data.get('sync', {}).get('rivals')
            if rivals:
                if rivals.get('nemesis'):
                    print(f"?? Nemesis Found: {rivals['nemesis']['name']} (Subs: {rivals['nemesis']['subs']})")
                if rivals.get('benchmark'):
                    print(f"? Benchmark Found: {rivals['benchmark']['name']} (Subs: {rivals['benchmark']['subs']})")
                
            # Check Quests
            quests = data.get('sync', {}).get('quests')
            if quests:
                print(f"?? Active Quests: {len(quests)}")
                for q in quests:
                    print(f"   - {q['type']}: Gap {q['gap']} (Reward: {q['reward_xp']} XP)")
        else:
            print(f"Simulation Failed: {res.status_code} - {res.text}")
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"Error during simulation: {e}")

    print("")
    print("--- Verification Complete ---")

if __name__ == "__main__":
    verify()
