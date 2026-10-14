@echo off
setlocal
cd /d "%~dp0.."
echo Building PushToTalk GUI Windows Executable...
echo.

REM Build the executable
echo Building GUI application with PyInstaller...
uv run --locked pyinstaller --noconfirm build_script/push_to_talk.spec
if errorlevel 1 (
    echo Build failed. Check the output above for errors.
    pause
    exit /b 1
)

REM Check if build was successful
if exist "dist\PushToTalk.exe" (
    echo.
    echo ========================================
    echo Build successful!
    echo GUI Executable created: dist\PushToTalk.exe
    echo ========================================
    echo.
    REM Compress the executable to a zip file for easy distribution
    echo Compressing executable to PushToTalk.zip...
    powershell -NoProfile -Command "Compress-Archive -LiteralPath dist\PushToTalk.exe -DestinationPath dist\PushToTalk.zip -Force"
    echo Executable compressed to PushToTalk.zip
    echo.

    echo To run the GUI application:
    echo 1. Double-click dist\PushToTalk.exe
    echo 2. Configure your selected provider's API key in the setup window
    echo 3. Adjust audio and hotkey settings as needed
    echo 4. Click "Start Application" to begin
    echo 5. Run as Administrator for hotkey detection
    echo.
    echo The application will show configuration dialogs on first run
    echo and then run in the background with your configured hotkeys.
    echo.

) else (
    echo.
    echo ========================================
    echo Build failed! Check the output above for errors.
    echo ========================================
    echo.
    echo Common issues:
    echo - Make sure uv is installed and working
    echo - Check that all dependencies are available
    echo - Ensure PyInstaller is in the dev dependencies
    echo.
)

pause
