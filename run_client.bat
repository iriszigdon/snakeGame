@echo off
setlocal

cd /d "%~dp0"

if not exist "snake_network\client\main.py" (
    echo Cannot find the project files.
    echo.
    echo This launcher must be inside the full project folder, next to:
    echo   snake_network\client\main.py
    echo.
    echo Do not copy only run_client.bat to another computer.
    echo Copy the whole snake project folder, then run this file from there.
    echo.
    pause
    exit /b 1
)

set "PYTHONPATH=%CD%"

set "SERVER_HOST=%~1"
if "%SERVER_HOST%"=="" (
    set /p SERVER_HOST=Enter server IP [127.0.0.1]: 
)
if "%SERVER_HOST%"=="" (
    set "SERVER_HOST=127.0.0.1"
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 -m snake_network.client.main --host "%SERVER_HOST%"
) else (
    python -m snake_network.client.main --host "%SERVER_HOST%"
)

if errorlevel 1 (
    echo.
    echo Client closed with an error.
    echo Make sure the server is running, Python is installed, and the IP address is correct.
    pause
)

endlocal
