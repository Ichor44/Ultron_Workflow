# Ultron - Single Server Launcher (merged Flask + Frontend)
# Runs EVERYTHING on port 5000: Flask Brain + Ultron Workflow UI
# Usage: powershell -ExecutionPolicy Bypass -File .\launch-ultron.ps1

$agentRoot = "C:\Users\Zaki\Documents\A.G.E.N.T"
$wfRoot = "$agentRoot\ultron-workflow"
Set-Location $agentRoot

Write-Host "== Ultron - Single Server (merged) ==" -ForegroundColor Cyan

# Ensure dist exists so / works
Write-Host "Checking frontend dist..." -ForegroundColor Yellow
if (-not (Test-Path "$wfRoot\dist\index.html")) {
  Write-Host "Building frontend dist first (one-time)..." -ForegroundColor DarkYellow
  Set-Location $wfRoot
  npm run build 1>nul 2>nul
  Set-Location $agentRoot
} else {
  Write-Host "Frontend dist already built." -ForegroundColor Green
}

# Start Brain (Flask on :5000 -- serves APIs AND workflow frontend at /)
Write-Host "Starting Brain (python web.py on :5000)" -ForegroundColor Yellow
Start-Process -FilePath python -ArgumentList "$agentRoot\web.py" -WorkingDirectory $agentRoot -WindowStyle Minimized
Start-Sleep -Seconds 3

# Done -- tell user the URL
Write-Host "=== Ultron Single Server ===" -ForegroundColor Cyan
Write-Host "All features available at: http://localhost:5000" -ForegroundColor Green
Write-Host "API endpoints at: http://localhost:5000/api" -ForegroundColor Cyan
Write-Host "Workflow, Protein Lab, DNA Lab, Chat, Mech Lab, Circuit Lab -- all in one browser tab" -ForegroundColor Green
Write-Host "Close this window to stop the servers" -ForegroundColor Cyan