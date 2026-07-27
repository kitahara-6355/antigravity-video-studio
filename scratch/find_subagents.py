import json
import re
from pathlib import Path

def main():
    log_path = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\065194c8-04f3-4708-9c18-94ccadff1f41\.system_generated\logs\transcript.jsonl")
    if not log_path.exists():
        print(f"Log path does not exist: {log_path}")
        return

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    invocations = []
    for i, line in enumerate(lines):
        try:
            step = json.loads(line)
            tool_calls = step.get("tool_calls", [])
            for tc in tool_calls:
                name = tc.get("name", "")
                if "invoke_subagent" in name:
                    args = tc.get("args", {})
                    subagents_raw = args.get("Subagents", "")
                    
                    # Extract target modules via regex if JSON load fails
                    targets = []
                    # Find all target modules inside prompt strings
                    # e.g., "対象モジュール: ([a-zA-Z0-9_/.-]+)"
                    matches = re.findall(r'対象モジュール:\s*([a-zA-Z0-9_/.-]+)', str(subagents_raw))
                    for m in matches:
                        targets.append(m)
                    
                    # If regex fails, fallback to general check
                    if not targets:
                        # Find "target_module" or similar if mentioned
                        pass
                        
                    # Find tool response in subsequent steps
                    conversation_ids = []
                    for j in range(i + 1, min(i + 15, len(lines))):
                        try:
                            f_step = json.loads(lines[j])
                            content_str = f_step.get("content", "")
                            if "conversationId" in content_str:
                                ids = re.findall(r'"conversationId":\s*"([^"]+)"', content_str)
                                if ids:
                                    conversation_ids = ids
                                    break
                        except Exception:
                            pass
                    
                    invocations.append({
                        "step_index": step.get("step_index"),
                        "targets": targets,
                        "conversation_ids": conversation_ids,
                        "raw_subagents": str(subagents_raw)[:100]
                    })
        except Exception as e:
            print(f"Error at line {i}: {e}")

    print(f"Parsed {len(invocations)} invocations of subagents in this session:")
    for inv in invocations:
        print(f"\nStep {inv['step_index']}:")
        targets = inv["targets"]
        conversation_ids = inv["conversation_ids"]
        max_len = max(len(targets), len(conversation_ids))
        for idx in range(max_len):
            target = targets[idx] if idx < len(targets) else "Unknown/Truncated"
            conv_id = conversation_ids[idx] if idx < len(conversation_ids) else "Pending/Not Found"
            print(f"  - Target: {target} -> ConvID: {conv_id}")

if __name__ == "__main__":
    main()
