@echo off
setlocal
cd /d "%~dp0"
if exist "dist\PushToTalk.exe" (
    start "" "%~dp0dist\PushToTalk.exe"
    exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b 0
)
echo The application has not been built and its Python environment is missing.
echo From this folder, run: uv sync --locked
echo Then double-click this launcher again.
pause
exit /b 1
