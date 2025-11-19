@echo off
echo [*] Building Wyzer Assistant EXE...

REM Activate local venv if it exists
IF EXIST .venv\Scripts\activate (
    call .venv\Scripts\activate
)

pyinstaller local_ai_assistant\gui\wyzer_chat_gui.py ^
  --name WyzerAssistant ^
  --paths . ^
  --hidden-import config ^
  --onedir ^
  --noconsole ^
  --clean ^
  --add-data "local_ai_assistant\data;data" ^
  --add-data "local_ai_assistant\models;models" ^
  --add-data "local_ai_assistant\tools;tools" ^
  --add-data "config.py;."

echo.
echo [*] Build complete!
echo EXE output folder: dist\WyzerAssistant
pause
