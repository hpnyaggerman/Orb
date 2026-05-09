@echo off

cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
    echo Error: git is not installed. Please install it from https://git-scm.com/downloads
    pause
    exit /b 1
)

for /f "tokens=*" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b
echo Current branch: %BRANCH%
echo Pulling latest changes...
echo.

git pull origin %BRANCH%

echo.
echo Update complete.
pause
