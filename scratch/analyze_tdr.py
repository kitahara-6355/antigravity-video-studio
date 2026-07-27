import json
from collections import Counter
from pathlib import Path

# パス設定
TDR_JSON_PATH = Path("backend/agents/memory/technical_debt_index.json")
OUTPUT_PATH = Path("C:/Users/PC_User/.gemini/antigravity/brain/4e1dd254-af6f-44a0-9575-5df303374338/scratch/tdr_analysis_summary.json")

def main():
    if not TDR_JSON_PATH.exists():
        print(f"Error: {TDR_JSON_PATH} not found.")
        return

    with open(TDR_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    print(f"Total entries: {len(entries)}")

    # 1. IMPORTANT_SERVICE (open)
    important_service_open = [e for e in entries if e.get("category") == "IMPORTANT_SERVICE" and e.get("status") == "open"]
    # 2. MINOR_INFRA (open)
    minor_infra_open = [e for e in entries if e.get("category") == "MINOR_INFRA" and e.get("status") == "open"]

    print(f"IMPORTANT_SERVICE open: {len(important_service_open)}")
    print(f"MINOR_INFRA open: {len(minor_infra_open)}")

    # IMPORTANT_SERVICE 分析
    imp_files = Counter([e.get("file_path") for e in important_service_open])
    imp_patterns = Counter([e.get("pattern") for e in important_service_open])
    imp_causes = Counter([e.get("cause_pattern") for e in important_service_open])

    # MINOR_INFRA 分析
    min_files = Counter([e.get("file_path") for e in minor_infra_open])
    min_patterns = Counter([e.get("pattern") for e in minor_infra_open])
    min_causes = Counter([e.get("cause_pattern") for e in minor_infra_open])

    summary = {
        "IMPORTANT_SERVICE": {
            "count": len(important_service_open),
            "files": dict(imp_files.most_common()),
            "patterns": dict(imp_patterns.most_common(20)),
            "causes": dict(imp_causes.most_common(10)),
            "details": [
                {
                    "debt_id": e.get("debt_id"),
                    "file_path": e.get("file_path"),
                    "line_number": e.get("line_number"),
                    "pattern": e.get("pattern"),
                    "cause_pattern": e.get("cause_pattern"),
                    "notes": e.get("notes")
                }
                for e in important_service_open
            ]
        },
        "MINOR_INFRA": {
            "count": len(minor_infra_open),
            "files": dict(min_files.most_common()),
            "patterns": dict(min_patterns.most_common(20)),
            "causes": dict(min_causes.most_common(10)),
            "details": [
                {
                    "debt_id": e.get("debt_id"),
                    "file_path": e.get("file_path"),
                    "line_number": e.get("line_number"),
                    "pattern": e.get("pattern"),
                    "cause_pattern": e.get("cause_pattern"),
                    "notes": e.get("notes")
                }
                for e in minor_infra_open
            ]
        }
    }

    # 出力
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Summary written to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
