Set-Location "C:\Users\syfsy\projekty\salonos"

function Is-PortListening($port) {
    $match = netstat -ano | Select-String ":$port\s+.*LISTENING"
    return [bool]$match
}

Write-Host "Starting SalonOS (API + BOT)..." -ForegroundColor Green

if (Is-PortListening 8000) {
    Write-Host "API already runs on port 8000, skipping API start." -ForegroundColor Cyan
} else {
    Start-Process powershell -ArgumentList "-NoExit","-Command","cd C:\Users\syfsy\projekty\salonos; .\start_api.ps1"
    Start-Sleep -Seconds 2
}

Start-Process powershell -ArgumentList "-NoExit","-Command","cd C:\Users\syfsy\projekty\salonos; .\start_bot.ps1"

Write-Host "SalonOS started." -ForegroundColor Cyan
