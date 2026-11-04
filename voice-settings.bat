@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Сначала установите проект через run.bat.
    pause
    exit /b 1
)
.venv\Scripts\python.exe voice_panel.py --open
pause
