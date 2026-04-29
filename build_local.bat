@echo off
setlocal

echo ============================================
echo   SoulClone - Local Build Script
echo ============================================
echo.

echo Please select your build target:
echo 1. Windows (Native)
echo 2. Linux (For package testing only. Will still produce a Windows binary.)
echo.
set /p target_choice="Enter 1 or 2: "

if "%target_choice%"=="1" (
    set BUILD_NAME=SoulClone-Windows
    set IS_LINUX=0
) else if "%target_choice%"=="2" (
    set BUILD_NAME=SoulClone-Linux
    set IS_LINUX=1
) else (
    echo Invalid choice. Exiting.
    pause
    exit /b 1
)

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

pyinstaller --onefile --name %BUILD_NAME% --collect-all lingua --collect-all chromadb --collect-all sentence_transformers main.py
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
if "%IS_LINUX%"=="0" (
    copy dist\%BUILD_NAME%.exe release_pkg\
) else (
    REM PyInstaller on Windows forces the .exe extension. This strips it for the Linux package.
    copy dist\%BUILD_NAME%.exe release_pkg\%BUILD_NAME%
    copy deploy\docker-binary\Dockerfile release_pkg\
    copy deploy\docker-binary\docker-compose.yml release_pkg\
)

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