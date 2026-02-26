Set-Location -Path $PSScriptRoot
& ".\.venv\Scripts\python.exe" -m bot.telegram_bot
Read-Host "SalonOS bot is running. Close this window to stop"
