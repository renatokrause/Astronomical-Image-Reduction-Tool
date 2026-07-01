@echo off
cd /d "%~dp0"

set "PYTHON_EXE=python"

%PYTHON_EXE% -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m pip install -e .

echo.
echo Environment setup complete.
echo Run AIRT.bat or scripts\run_qt_dev.ps1.
pause
