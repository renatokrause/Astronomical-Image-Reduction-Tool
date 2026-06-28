@echo off
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Python 3.12 was not found at:
    echo %PYTHON_EXE%
    echo Install Python 3.12 before running this setup script.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo Environment setup complete.
pause
