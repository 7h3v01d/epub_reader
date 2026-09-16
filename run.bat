@echo off
REM SPDX-License-Identifier: Apache-2.0
REM Launch the PyQt6 EPUB reader. Optional arg: a path to an .epub to open.
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

set "PYTHONPATH=%~dp0src"
"%PY%" -m epubreader.frontends.qt.app %*
endlocal
