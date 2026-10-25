@echo off
setlocal
cd /d "%~dp0"
set "WORDCEL_PYTHON=.venv-desktop\Scripts\pythonw.exe"
if not exist "%WORDCEL_PYTHON%" set "WORDCEL_PYTHON=.venv\Scripts\pythonw.exe"
if not exist "%WORDCEL_PYTHON%" (
    echo Wordcel needs its Python environment. See the project setup instructions.
    pause
    exit /b 1
)
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
start "" "%WORDCEL_PYTHON%" -m wordcel.scripts.quick_lookup %*
