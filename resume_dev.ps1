# Antigravity Smart Resume Script
# Purpose: Cleanly restart the development environment by killing conflicts and verifying health.

Write-Host "🚀 Starting Antigravity System Resume Procedure..." -ForegroundColor Cyan

Write-Host "🚀 Starting Antigravity System Resume Procedure..." -ForegroundColor Cyan

# 0. Environment Self-Healing (Dependency Check)
Write-Host "🔧 Verifying Environment Integrity..." -ForegroundColor DarkGray
$rootPath = "c:/Users/PC_User/Desktop/script/video-automation"
$venvRoot = "c:/Users/PC_User/Desktop/script/vault-environments/.venv"
$venvPip = "$venvRoot/Scripts/pip.exe"
$venvPython = "$venvRoot/Scripts/python.exe"
$reqFile = "$rootPath/backend/requirements.txt"

if (Test-Path $venvPip) {
    Write-Host "   Running dependency check (vault-environments)..." -NoNewline
    $null = & $venvPip install -r $reqFile -q
    Write-Host " Done." -ForegroundColor Green
}
else {
    Write-Host "⚠️ Warning: Venv not found at $venvPip" -ForegroundColor Yellow
}

# 1. Kill Conflicting Processes
Write-Host "🧹 Cleaning up port conflicts..." -ForegroundColor Yellow
$ports = @(8000, 5173)
foreach ($port in $ports) {
    $process = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if ($process) {
        Write-Host "   Killing process '$process' on port $port" -ForegroundColor Red
        Stop-Process -Id $process -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

# 2. Start Backend
Write-Host "🧠 Launching Backend Brain..." -ForegroundColor Green
$backendPath = "c:/Users/PC_User/Desktop/script/video-automation/backend"
$backendScript = "cd '$backendPath'; & '$venvPython' -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass", "-NoExit", "-Command", $backendScript -WindowStyle Minimized

# 3. Start Frontend
Write-Host "🎨 Launching Frontend Matrix..." -ForegroundColor Green
$frontendPath = "c:/Users/PC_User/Desktop/script/video-automation/frontend"
$frontendScript = "cd '$frontendPath'; npm run dev"
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass", "-NoExit", "-Command", $frontendScript -WindowStyle Minimized

# 4. Deep Health Check
Write-Host "🏥 Waiting for Critical Vitals (API Status)..." -ForegroundColor Yellow
$maxRetries = 30
$retryCount = 0
$healthy = $false

while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/status" -Method Get -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            Write-Host "✅ Backend is ALIVE and Responsive!" -ForegroundColor Green
            break
        }
    }
    catch {
        Write-Host "   ...waiting for connection ($retryCount/$maxRetries)" -ForegroundColor DarkGray
    }
    Start-Sleep -Seconds 2
    $retryCount++
}

if ($healthy) {
    Write-Host "🚀 System Green. Launching Interface." -ForegroundColor Cyan
    Start-Process "http://localhost:5173"
}
else {
    Write-Host "❌ CRITICAL: Backend failed to initialize. Check backend terminal for errors." -ForegroundColor Red
    exit 1
}
