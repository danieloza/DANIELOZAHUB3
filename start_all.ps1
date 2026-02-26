Set-Location -Path $PSScriptRoot

function Is-PortListening($port) {
    $match = netstat -ano | Select-String ":$port\s+.*LISTENING"
    return [bool]$match
}

Write-Host "Starting SalonOS (API + BOT)..." -ForegroundColor Green

$apiScript = Join-Path $PSScriptRoot "start_api.ps1"
$botScript = Join-Path $PSScriptRoot "start_bot.ps1"

if (Is-PortListening 8000) {
    Write-Host "API already runs on port 8000, skipping API start." -ForegroundColor Cyan
} else {
    Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit", "-File", $apiScript
    Start-Sleep -Seconds 2
}

Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit", "-File", $botScript

Write-Host "SalonOS started." -ForegroundColor Cyan
