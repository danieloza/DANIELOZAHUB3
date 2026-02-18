@echo off
echo ===============================
echo     DANEX ??? START SYSTEMU
echo ===============================

REM === SALONOS API ===
echo [1/3] Uruchamiam SalonOS API...
start "SalonOS API" cmd /k ^
cd /d C:\Users\syfsy\projekty\salonos ^& ^
.venv\Scripts\activate ^& ^
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

timeout /t 3 >nul

REM === SALONOS BOT ===
echo [2/3] Uruchamiam SalonOS BOT...
start "SalonOS BOT" cmd /k ^
cd /d C:\Users\syfsy\projekty\salonos ^& ^
.venv\Scripts\activate ^& ^
python -m bot.telegram_bot

timeout /t 2 >nul

REM === STOP STAREJ INSTANCJI DANEX ===
echo [3/3] Zatrzymuje poprzednia instancje Danex BOT (jesli dziala)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'danex-faktury-bot\\bot.py' } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul
timeout /t 1 >nul

REM === DANEX FAKTURY BOT ===
echo [3/3] Uruchamiam Danex Faktury BOT...
start "Danex Faktury BOT" cmd /k ^
cd /d C:\Users\syfsy\danex-faktury-bot ^& ^
call .venv\Scripts\activate.bat ^& ^
python --version ^& ^
python bot.py


echo ===============================
echo   WSZYSTKO URUCHOMIONE
echo ===============================
pause

