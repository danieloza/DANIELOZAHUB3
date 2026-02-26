Set-Location -Path $PSScriptRoot
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Read-Host "SalonOS API is running. Close this window to stop"
