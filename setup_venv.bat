@echo off
REM SPDX-License-Identifier: Apache-2.0
REM Create the local virtual environment and install dependencies.
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

echo.
echo Done. Use run.bat to launch, or run tests with:
echo     .venv\Scripts\activate ^&^& python -m pytest
endlocal
