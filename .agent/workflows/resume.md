---
description: Cleanly restarts the Antigravity development environment (Backend + Frontend) after PC reboot or crash.
---

1. Run the Smart Resume PowerShell script.
// turbo
powershell -ExecutionPolicy Bypass -File "c:/Users/PC_User/Desktop/script/video-automation/resume_dev.ps1"

2. If resume_dev.ps1 stalls on health check or servers fail to start, use the manual fallback (M3.6 G2-G4 session で確立):
// turbo
Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory "c:/Users/PC_User/Desktop/script/video-automation/backend" -WindowStyle Hidden

// turbo
Start-Process -FilePath "cmd" -ArgumentList "/c", "npm run dev -- --host --port 5173" -WorkingDirectory "c:/Users/PC_User/Desktop/script/video-automation/frontend" -WindowStyle Hidden

3. Verify both servers are running:
// turbo
python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health'); print('Backend:', r.status); r2=urllib.request.urlopen('http://127.0.0.1:5173/'); print('Frontend:', r2.status)"

> [!NOTE]
> - Frontend must be started via `cmd /c` — direct `npm` invocation from PowerShell fails
> - `0.0.0.0` binding is required for backend; `127.0.0.1` causes connection failures from Playwright
> - `netstat` may show TIME_WAIT entries from previous sessions — these are not active listeners

