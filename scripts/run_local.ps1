# AI ComicVerse - one-shot local launcher (Windows / PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1
#
# Creates a venv, installs the backend, starts uvicorn in a new window, installs
# the frontend and starts Vite. Add GEMINI_API_KEY to backend\.env for Gemini;
# Pollinations is used for panel images by default.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv = Join-Path $backend '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

Write-Host '=== AI ComicVerse : local run ===' -ForegroundColor Cyan

if (-not (Test-Path $python)) {
    Write-Host '-> creating the backend virtualenv'
    python -m venv $venv
}

Write-Host '-> installing backend dependencies'
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r (Join-Path $backend 'requirements.txt') --quiet

if (-not (Test-Path (Join-Path $backend '.env'))) {
    Copy-Item (Join-Path $backend '.env.example') (Join-Path $backend '.env')
    Write-Host '-> created backend\.env from .env.example; add GEMINI_API_KEY for Gemini text analysis' -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host '-> installing frontend dependencies'
    Push-Location $frontend
    npm install --no-audit --no-fund
    Pop-Location
}

Write-Host '-> starting the API on http://127.0.0.1:8000 (docs at /docs)'
Start-Process -FilePath $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload' -WorkingDirectory $backend

Start-Sleep -Seconds 3

Write-Host '-> starting the UI on http://localhost:5173'
Start-Process -FilePath 'npm' -ArgumentList 'run', 'dev' -WorkingDirectory $frontend

Write-Host ''
Write-Host 'Open http://localhost:5173, enter a story, and generate your comic.' -ForegroundColor Green
Write-Host 'Stop with: Get-Process | Where-Object { $_.ProcessName -in "python","node" } | Stop-Process'
