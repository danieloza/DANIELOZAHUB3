# Kill Python processes running from this venv that are orphan
Get-Process python | Where-Object { $_.Path -like "*salonos*" } | Stop-Process -Force
Write-Host "Zombies killed."
