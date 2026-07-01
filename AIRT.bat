@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

set "PYTHONPATH=%CD%\src"
"%PYTHON_EXE%" -m airt
