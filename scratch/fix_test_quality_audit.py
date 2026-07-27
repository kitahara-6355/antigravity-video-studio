import shutil
from pathlib import Path

def main():
    session_id = "c62ea2d3-95c1-4525-8ffe-1a1776e680c2"
    src = Path(f"C:/Users/PC_User/.gemini/antigravity/brain/{session_id}/.system_generated/worktrees/subagent-bug-hunter-Agent-000-self-923470f8/backend/tests/test_quality_audit_fixes.py")
    dst = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/tests/test_quality_audit_fixes.py")

    # Copy the file
    shutil.copy2(src, dst)
    print("Copied file from worktree.")

    # Read content
    content = dst.read_text(encoding="utf-8")

    # Replace only inside TestGeminiClientFactory class
    parts = content.split("class TestGeminiClientFactory:")
    if len(parts) == 2:
        class_body = parts[1]
        class_body = class_body.replace("gemini_client_factory._client", "gemini_client_factory._cached_raw_client")
        class_body = class_body.replace("gemini_client_factory._governed_client", "gemini_client_factory._cached_governed_client")
        class_body = class_body.replace("patch.object(gemini_client_factory, '_client'", "patch.object(gemini_client_factory, '_cached_raw_client'")
        
        new_content = parts[0] + "class TestGeminiClientFactory:" + class_body
        dst.write_text(new_content, encoding="utf-8")
        print("Replaced cache fields successfully in TestGeminiClientFactory.")
    else:
        print("Error: TestGeminiClientFactory class not found uniquely.")

if __name__ == "__main__":
    main()
