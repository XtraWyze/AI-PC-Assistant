@echo off
setlocal enabledelayedexpansion

REM Resolve project root relative to this batch file.
set "PROJECT_ROOT=%~dp0"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "APP_DIR=%PROJECT_ROOT%\local_ai_assistant"

if not exist "%APP_DIR%\assistant.py" (
    echo [ERROR] Could not find assistant.py in "%APP_DIR%".
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo [ERROR] Python venv not found at "%VENV_PY%".
    echo Run "py -3 -m venv .venv" then install requirements before retrying.
    exit /b 1
)

pushd "%APP_DIR%"
echo [INFO] Launching local AI assistant...
"%VENV_PY%" assistant.py %*
popd

endlocal
