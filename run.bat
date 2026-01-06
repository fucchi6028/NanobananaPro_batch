@echo off
chcp 65001 >nul
title Nanobananapro Batch Generator

echo ========================================
echo  Nanobananapro Batch Generator
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install/update dependencies
echo [INFO] Checking dependencies...
pip install -r requirements.txt -q

REM Create outputs folder
if not exist "outputs" mkdir outputs

REM Run the app
echo.
echo [INFO] Starting Gradio server...
echo [INFO] Opening browser at http://127.0.0.1:7860
echo.
python app.py

pause
