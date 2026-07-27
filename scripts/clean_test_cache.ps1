<#
.SYNOPSIS
    テストキャッシュの一括削除スクリプト

.DESCRIPTION
    Phase 1 M1.1 T-009: Whisperキャッシュ、pytest/pycacheを削除し、
    クリーン状態でのテスト実行を保証する。
    MASTER v3.6 原則2: キャッシュ依存テストを禁じる

.EXAMPLE
    .\scripts\clean_test_cache.ps1
    .\scripts\clean_test_cache.ps1 -DryRun
#>

param(
    [switch]$DryRun
)

$root = Split-Path -Parent $PSScriptRoot
if (-not $root) { $root = Get-Location }

Write-Host "[CLEAN] Test cache deletion started: $root"

# 1. Whisper cache (_whisper_*.jsonl)
$whisperFiles = Get-ChildItem -Path $root -Recurse -Filter "_whisper_*.jsonl" -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -notlike "*fixtures*" }
Write-Host "  Whisper cache: $($whisperFiles.Count) files"
if (-not $DryRun) {
    $whisperFiles | Remove-Item -Force -ErrorAction SilentlyContinue
}

# 2. __pycache__ directories
$pycache = Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
Write-Host "  __pycache__: $($pycache.Count) dirs"
if (-not $DryRun) {
    $pycache | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

# 3. .pytest_cache directories
$pytestCache = Get-ChildItem -Path $root -Recurse -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue
Write-Host "  .pytest_cache: $($pytestCache.Count) dirs"
if (-not $DryRun) {
    $pytestCache | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

# 4. .coverage files
$coverage = Get-ChildItem -Path $root -Recurse -Filter ".coverage" -File -ErrorAction SilentlyContinue
Write-Host "  .coverage: $($coverage.Count) files"
if (-not $DryRun) {
    $coverage | Remove-Item -Force -ErrorAction SilentlyContinue
}

# Verification
if (-not $DryRun) {
    $remaining = Get-ChildItem -Path $root -Recurse -Filter "_whisper_*.jsonl" -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -notlike "*fixtures*" -and $_.DirectoryName -notlike "*test_videos*" }
    if ($remaining.Count -eq 0) {
        Write-Host "[OK] Test cache deletion complete"
    }
    else {
        Write-Host "[WARN] Remaining files: $($remaining.Count)"
        $remaining | ForEach-Object { Write-Host "  $_" }
    }
}
else {
    Write-Host "[DRY-RUN] No files were deleted"
}
