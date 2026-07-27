import json
from pathlib import Path

SUMMARY_PATH = Path("C:/Users/PC_User/.gemini/antigravity/brain/4e1dd254-af6f-44a0-9575-5df303374338/scratch/tdr_analysis_summary.json")

def main():
    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    infra = data.get("MINOR_INFRA", {})
    print("=== MINOR_INFRA SUMMARY ===")
    print(f"Total Count: {infra.get('count')}")
    
    print("\nTop Files:")
    for file, count in list(infra.get("files", {}).items())[:20]:
        print(f"  {file}: {count}")

    print("\nTop Patterns:")
    for pat, count in list(infra.get("patterns", {}).items())[:10]:
        print(f"  {pat}: {count}")

    print("\nTop Causes:")
    for cause, count in list(infra.get("causes", {}).items())[:10]:
        print(f"  {cause}: {count}")

if __name__ == "__main__":
    main()
