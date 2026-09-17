@echo off
REM SPDX-License-Identifier: Apache-2.0
REM Create the local virtual environment and install dependencies.
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: failed to create virtual environment.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: pip upgrade failed.
    exit /b 1
)
python -m pip install -r requirements-dev.txt
if errorlevel 1 (
    echo ERROR: dependency installation failed.
    exit /b 1
)

echo.
echo Done. Use run.bat to launch, or run tests with:
echo     .venv\Scripts\activate ^&^& python -m pytest
endlocal
