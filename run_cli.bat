@echo off
REM SPDX-License-Identifier: Apache-2.0
REM Launch the terminal reader. Requires a path to an .epub.
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

set "PYTHONPATH=%~dp0src"
"%PY%" -m epubreader.frontends.cli.app %*
endlocal
