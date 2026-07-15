@echo off
setlocal

cd /d "%~dp0"

set "SERVER_HOST=%~1"
if "%SERVER_HOST%"=="" (
    set "SERVER_HOST=0.0.0.0"
)

set "SERVER_PORT=%~2"
if "%SERVER_PORT%"=="" (
    set "SERVER_PORT=5050"
)

echo Starting Network Snake server...
echo Host: %SERVER_HOST%
echo Port: %SERVER_PORT%
echo.
echo Clients on this computer can connect to: 127.0.0.1
echo Clients on another computer should connect to this computer's IPv4 address.
echo To find it, open another terminal and run: ipconfig
echo.

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 -m snake_network.server.main --host "%SERVER_HOST%" --port "%SERVER_PORT%"
) else (
    python -m snake_network.server.main --host "%SERVER_HOST%" --port "%SERVER_PORT%"
)

echo.
echo Server stopped.
pause

endlocal
