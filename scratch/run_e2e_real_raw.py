import os
import sys
import time
import urllib.request
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

# Artifact directory to save screenshots
ARTIFACT_DIR = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\85253b88-e891-4a1c-b422-be5d7e0a8140")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def get_pipeline_status():
    try:
        req = urllib.request.Request("http://localhost:8000/api/pipeline/status")
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print("Error fetching pipeline status:", e)
        return None

def run_e2e():
    print("Starting Playwright E2E Video Automation Flow with 1.1GB Real RAW Videos...")
    
    # Force reset pipeline state before launching Playwright
    try:
        print("Sending force-reset request to backend API...")
        req = urllib.request.Request("http://localhost:8000/api/pipeline/force-reset", method="POST")
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            print("Force-reset API response:", res_data)
    except Exception as e:
        print("Failed to reset pipeline state:", e)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        # Monitor browser console logs
        page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))
        page.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}"))

        print("Navigating to Antigravity Video Studio UI and setting bypass for onboarding...")
        page.goto("http://localhost:5173")
        page.wait_for_timeout(1000)
        page.evaluate("localStorage.setItem('antigravity_onboarded', 'true')")
        page.goto("http://localhost:5173", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Take initial screenshot before opening modal
        page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step1_before_modal.png"))

        print("Opening pipeline modal...")
        btn = page.locator("button:has-text('制作する')").first
        if not btn.is_visible():
            btn = page.locator("text=制作する").first
        
        btn.wait_for(state="visible", timeout=10000)
        btn.click(force=True)
        
        print("Waiting 8s for videos list API loading...")
        page.wait_for_timeout(8000)

        page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step1_after_load_wait.png"))

        # Print all folder items visible in the DOM for debugging
        print("Debugging available folder items:")
        items = page.locator("div.pipeline-video-item")
        count = items.count()
        print(f"Total pipeline-video-item elements found: {count}")
        for i in range(count):
            print(f"Item {i}: {items.nth(i).text_content()}")

        # ----------------------------------------------------
        # Step 1: Material Selection
        # ----------------------------------------------------
        print("Step 1: Selecting folders...")
        
        # Deselect test folder if selected
        try:
            rec_folder_row = page.locator("div.pipeline-video-item", has=page.locator("span", has_text="2025-09_Recording"))
            if rec_folder_row.count() > 0:
                deselect_btn = rec_folder_row.locator("button").first
                txt = deselect_btn.text_content() or ""
                if "✓" in txt:
                    print("Deselecting 2025-09_Recording folder...")
                    deselect_btn.click(force=True)
                    page.wait_for_timeout(1500)
        except Exception as e:
            print("Failed to deselect test folder:", e)

        # Select real raw folder
        target_folder_row = None
        for name_candidate in ["本番RAW01 対談_山田", "RAW01", "山田"]:
            row = page.locator("div.pipeline-video-item", has=page.locator("span", has_text=name_candidate))
            if row.count() > 0:
                target_folder_row = row
                print(f"Found folder row matching candidate: '{name_candidate}'")
                break

        if target_folder_row is None:
            if count > 1:
                target_folder_row = items.nth(1)
                print("Fallback: Using the second folder item in the list")

        if target_folder_row is not None:
            target_folder_row.scroll_into_view_if_needed()
            select_btn = target_folder_row.locator("button").first
            txt = select_btn.text_content() or ""
            if "✓" not in txt:
                print(f"Selecting target folder (text: {target_folder_row.text_content().strip()})...")
                select_btn.click(force=True)
                page.wait_for_timeout(1500)
            else:
                print("Target folder is already selected.")

        print("Capturing Step 1 screenshot: Material Selection")
        page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step1_selection.png"))

        # Click Start Pipeline
        start_btn = page.locator("button:has-text('パイプライン開始'), .pipeline-start-btn").first
        start_btn.wait_for(state="attached", timeout=5000)
        print("Clicking Start Pipeline button...")
        start_btn.click(force=True)
        page.wait_for_timeout(3000)

        # ----------------------------------------------------
        # Step 2 & 3: Monitoring progress using API status
        # ----------------------------------------------------
        print("Step 2: Processing - waiting for transcription/Whisper...")
        transcription_screenshotted = False
        
        # Poll pipeline status API
        max_minutes = 45
        for attempt in range(max_minutes * 6):  # Poll every 10 seconds
            status = get_pipeline_status()
            if status is None:
                time.sleep(10)
                continue
                
            p_status = status.get("status")
            stages = status.get("stages", [])
            
            # Stages mapping (approximate index):
            # 0: Transcription, 1: AI Proofread, 2: SmartCut, 3: Quality Gate, 4: Render
            print(f"[{time.strftime('%H:%M:%S')}] Pipeline API: status={p_status}, stages={ [s.get('name') + ':' + s.get('status') for s in stages] }")

            # Capture Transcription screenshot once running
            if len(stages) > 0 and stages[0].get("status") == "running" and not transcription_screenshotted:
                print("Capturing Step 2 screenshot: Transcription in progress...")
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step2_transcription.png"))
                transcription_screenshotted = True

            # If we reached SmartCut stage (stages[2] running/pending, or current stage index indicates SmartCut)
            # Or if SmartCut panel elements are visible on screen
            smartcut_visible = page.locator("button:has-text('品質ゲートへ'), button:has-text('確定')").count() > 0
            if smartcut_visible or (len(stages) > 2 and stages[2].get("status") in ("running", "active")):
                print("Step 3: SmartCut Configuration page reached!")
                page.wait_for_timeout(3000)
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step3_smartcut.png"))
                
                print("Clicking next stage button in SmartCut...")
                next_btn = page.locator("button:has-text('品質ゲートへ'), button:has-text('次へ'), button:has-text('確定')").first
                next_btn.click(force=True)
                page.wait_for_timeout(5000)
                break
                
            if p_status == "error":
                print(f"Error in pipeline: {status.get('error')}")
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_error.png"))
                sys.exit(1)
                
            time.sleep(10)
        else:
            print("Timeout waiting for SmartCut stage.")
            page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_timeout_smartcut.png"))

        # ----------------------------------------------------
        # Step 4: Quality Gate & AI Suggestions
        # ----------------------------------------------------
        print("Step 4: Quality Gate evaluation...")
        # Poll for Quality Gate stage
        for attempt in range(30):
            status = get_pipeline_status()
            stages = status.get("stages", []) if status else []
            
            # Directly click render button if visible to finalize the export
            render_btn = page.locator("button:has-text('レンダリング開始'), button:has-text('強制的に書き出す'), button:has-text('書き出し')").first
            if render_btn.count() > 0 and render_btn.is_visible():
                print("Quality Gate UI and Render button detected!")
                page.wait_for_timeout(2000)
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step4_qualitygate.png"))
                
                print("Clicking Render/Export video button directly...")
                render_btn.click(force=True)
                page.wait_for_timeout(3000)
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step4_applied_suggestion.png"))
                break
                
            apply_btn = page.locator("button:has-text('適用'), button:has-text('AI提案を適用')").first
            if apply_btn.count() > 0 and apply_btn.is_visible():
                print("Quality Gate UI detected (only Apply button visible)...")
                page.wait_for_timeout(2000)
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step4_qualitygate.png"))
                
                print("Applying AI suggestion...")
                apply_btn.click(force=True)
                page.wait_for_timeout(3000)
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step4_applied_suggestion.png"))
                break
            time.sleep(5)

        # ----------------------------------------------------
        # Step 5: Rendering and Completion
        # ----------------------------------------------------
        print("Step 5: Waiting for video encoding to finish...")
        for attempt in range(120):  # Wait up to 20 minutes (120 * 10s)
            status = get_pipeline_status()
            p_status = status.get("status") if status else "unknown"
            
            print(f"[{time.strftime('%H:%M:%S')}] Render status check: {p_status}")
            
            body_text = page.locator("body").text_content() or ""
            if "書き出し完了" in body_text or "完了" in body_text or "保存されました" in body_text or p_status == "completed":
                print("Encoding completed successfully!")
                page.wait_for_timeout(3000)
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step5_complete.png"))
                break
                
            if p_status == "error":
                print(f"Error during rendering: {status.get('error')}")
                page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_render_error.png"))
                sys.exit(1)
                
            time.sleep(10)
        else:
            print("Timeout waiting for video render completion.")
            page.screenshot(path=str(ARTIFACT_DIR / "real_e2e_step5_timeout.png"))

        browser.close()
        print("Playwright E2E Video Flow execution ended.")

if __name__ == "__main__":
    run_e2e()
