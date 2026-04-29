@echo off
setlocal

echo ============================================
echo   SoulClone - Linux Cached Build Script
echo ============================================
echo.

echo Checking for cached compiler image...
docker image inspect soulclone-compiler:latest >nul 2>&1
if errorlevel 1 (
    echo Cached image not found.
    echo Building cached Docker image. This will take a few minutes but only happens once.
    docker build -t soulclone-compiler:latest -f Dockerfile.compiler .
    if errorlevel 1 (
        echo ERROR: Docker image build failed.
        pause
        exit /b 1
    )
) else (
    echo Cached image found. Proceeding to rapid compile.
)

echo.
echo Booting temporary Linux container to compile binary...

REM -v "%cd%":/src maps your current Windows folder into the cached Linux container
docker run --rm -v "%cd%":/src -w /src soulclone-compiler:latest bash -c "pyinstaller --onefile --name SoulClone-Linux --collect-all lingua --collect-all chromadb --collect-all sentence_transformers main.py"

if errorlevel 1 (
    echo ERROR: PyInstaller compilation failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo Compilation complete! 
echo Your native Linux binary is waiting inside the 'dist' folder.
echo ============================================
pause