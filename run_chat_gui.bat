@echo off
setlocal enabledelayedexpansion

REM Launch the Wyzer chat GUI with the project virtual environment.
set "PROJECT_ROOT=%~dp0"
set "VENV_DIR=%PROJECT_ROOT%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PYW=%VENV_DIR%\Scripts\pythonw.exe"
set "APP_DIR=%PROJECT_ROOT%\local_ai_assistant"
set "REQUIREMENTS_FILE=%APP_DIR%\requirements.txt"
set "ENTRY_MODULE=gui.wyzer_chat_gui"

if not exist "%APP_DIR%\%ENTRY_MODULE:.=\%.py" (
    echo [ERROR] Could not find %ENTRY_MODULE% in "%APP_DIR%".
    exit /b 1
)

if not exist "%REQUIREMENTS_FILE%" (
    echo [ERROR] requirements.txt missing at "%REQUIREMENTS_FILE%".
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo [INFO] Python venv not found. Creating one under "%VENV_DIR%"...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Ensure Python 3 is installed and "py" is on PATH.
        exit /b 1
    )
    echo [INFO] Upgrading pip inside the virtual environment...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 (
        echo [ERROR] Failed to upgrade pip. Aborting.
        exit /b 1
    )
    echo [INFO] Installing project requirements...
    "%VENV_PY%" -m pip install -r "%REQUIREMENTS_FILE%"
    if errorlevel 1 (
        echo [ERROR] pip install failed. Review the messages above.
        exit /b 1
    )
)

pushd "%APP_DIR%"
set "PY_EXEC=%VENV_PYW%"
if not exist "%PY_EXEC%" (
    echo [WARN] pythonw.exe missing; falling back to console python.
    set "PY_EXEC=%VENV_PY%"
)
echo [INFO] Launching Wyzer chat GUI...
start "WyzerGUI" /b "%PY_EXEC%" -m %ENTRY_MODULE% %*
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo [WARN] Failed to launch GUI (start error %EXIT_CODE%).
)

endlocal & exit /b %EXIT_CODE%
