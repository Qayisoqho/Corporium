@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "CORPORIUM_PYTHON=%~dp0.desktop-venv\Scripts\pythonw.exe"
if not exist "%CORPORIUM_PYTHON%" set "CORPORIUM_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%CORPORIUM_PYTHON%" (
    echo Create a Python environment first. See README.md.
    pause
    exit /b 1
)
start "" "%CORPORIUM_PYTHON%" "%~dp0desktop.py" --dev
exit /b
