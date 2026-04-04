@echo off
setlocal

echo ============================================
echo  Lustsoul Discord Persona - Environment Setup
echo ============================================
echo.

REM Create virtual environment
if exist .venv (
    echo Virtual environment already exists, skipping creation.
) else (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        echo Make sure Python 3.8+ is installed and on your PATH.
        pause
        exit /b 1
    )
    echo Done.
)

echo.

REM Activate and install dependencies
echo Installing dependencies from requirements.txt...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Setup complete. Environment is now active.
echo  You can now run commands like:
echo    python main.py preprocess
echo ============================================
echo.

REM Keep the window open and interactive with the activated environment
cmd /k