@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto error
    .venv\Scripts\python.exe -m pip install -e .
    if errorlevel 1 goto error
)
echo 1. Voice mode - current Windows microphone (local / remote)
echo 6. Voice mode - Fifine microphone
echo 2. Text chat
echo 3. Diagnostics
echo 4. Install / update dependencies
echo 5. Import sample inventory into empty database
set /p choice="Choose [1-6]: "
if "%choice%"=="1" .venv\Scripts\python.exe main.py listen
if "%choice%"=="6" .venv\Scripts\python.exe main.py listen --microphone fifine
if "%choice%"=="2" .venv\Scripts\python.exe main.py chat
if "%choice%"=="3" .venv\Scripts\python.exe main.py doctor --audio-test --stt-test
if "%choice%"=="4" (
    .venv\Scripts\python.exe -m ensurepip --upgrade
    .venv\Scripts\python.exe -m pip install -e .
)
if "%choice%"=="5" .venv\Scripts\python.exe main.py import-inventory examples/sklad_example.json
pause
exit /b
:error
echo Setup failed. Check Python and internet connection.
pause
exit /b 1
