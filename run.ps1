# Nanobananapro Batch Generator - PowerShell Launcher

$Host.UI.RawUI.WindowTitle = "Nanobananapro Batch Generator"

Write-Host "========================================"
Write-Host "  Nanobananapro Batch Generator"
Write-Host "========================================"
Write-Host ""

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[INFO] $pythonVersion"
} catch {
    Write-Host "[ERROR] Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from https://python.org"
    Read-Host "Press Enter to exit"
    exit 1
}

# Check/create virtual environment
if (-not (Test-Path "venv")) {
    Write-Host "[INFO] Creating virtual environment..."
    python -m venv venv
}

# Activate virtual environment
& .\venv\Scripts\Activate.ps1

# Install dependencies
Write-Host "[INFO] Checking dependencies..."
pip install -r requirements.txt -q

# Create outputs folder
if (-not (Test-Path "outputs")) {
    New-Item -ItemType Directory -Path "outputs" | Out-Null
}

# Run app
Write-Host ""
Write-Host "[INFO] Starting Gradio server..."
Write-Host "[INFO] Opening browser at http://127.0.0.1:7860"
Write-Host ""

python app.py

Read-Host "Press Enter to exit"
