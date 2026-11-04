@echo off
chcp 65001 > nul
title Maker Assistant

echo ====================================================
echo           MAKER ASSISTANT (ALWAYS-ON)
echo ====================================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH!
    pause
    exit /b 1
)

echo.
echo 1) Запустить голосовой режим (Always-On)
echo 2) Запустить текстовый режим (Чат / Тест)
echo 3) Установить зависимости (pip install)
echo.

set /p choice="Выберите действие [1-3]: "

if "%choice%"=="1" (
    python main.py listen
) else if "%choice%"=="2" (
    python main.py chat
) else if "%choice%"=="3" (
    pip install -r requirements.txt
    pause
) else (
    echo Неверный выбор!
    pause
)
