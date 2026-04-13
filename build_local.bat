@echo off
setlocal

echo ============================================
echo   SoulClone - Local Windows Build Script
echo ============================================
echo.

REM Activate virtual environment
if exist .venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo ERROR: Virtual environment not found!
    echo Please run setup.bat or setup-dev.bat first to create the .venv.
    pause
    exit /b 1
)
echo.

REM Ensure pyinstaller is installed inside the venv
echo Checking/Installing PyInstaller...
pip install pyinstaller
echo.

REM Run PyInstaller with the optimized arguments
echo Building Executable...
pyinstaller --onefile --name SoulClone-Windows --collect-all lingua --exclude-module pandas.tests main.py

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed!
    pause
    exit /b 1
)

echo.
echo Preparing local test package in 'release_pkg'...
if exist release_pkg rmdir /S /Q release_pkg
mkdir release_pkg

REM Copy all release assets exactly as defined in python-app.yml
copy dist\SoulClone-Windows.exe release_pkg\
copy config.yaml release_pkg\
copy .env.example release_pkg\
copy LICENSE release_pkg\
copy README.md release_pkg\
xcopy docs release_pkg\docs\ /E /I /Y > NUL
xcopy notebooks release_pkg\notebooks\ /E /I /Y > NUL

echo.
echo ============================================
echo Build complete! 
echo Your fully packaged testing environment is ready inside the 'release_pkg' folder.
echo ============================================
pause