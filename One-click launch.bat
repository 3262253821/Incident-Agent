@echo off
setlocal

set "INCIDENT_ROOT=E:\IncidentAgent"
set "DEVATLAS_ROOT=E:\RagKnowledgeSystem"
set "SCRIPT_ROOT=E:\IncidentAgent\scripts"

if not exist "%DEVATLAS_ROOT%\backend" (
    echo [ERROR] DevAtlas backend directory not found: %DEVATLAS_ROOT%\backend
    pause
    exit /b 1
)

if not exist "%INCIDENT_ROOT%\app\main.py" (
    echo [ERROR] Incident Agent entrypoint not found: %INCIDENT_ROOT%\app\main.py
    pause
    exit /b 1
)

if not exist "%INCIDENT_ROOT%\web\package.json" (
    echo [ERROR] Incident Agent frontend not found: %INCIDENT_ROOT%\web\package.json
    pause
    exit /b 1
)

if not exist "%SCRIPT_ROOT%\start-devatlas.ps1" (
    echo [ERROR] DevAtlas start script not found: %SCRIPT_ROOT%\start-devatlas.ps1
    pause
    exit /b 1
)

if not exist "%SCRIPT_ROOT%\start-agent.ps1" (
    echo [ERROR] Agent start script not found: %SCRIPT_ROOT%\start-agent.ps1
    pause
    exit /b 1
)

if not exist "%SCRIPT_ROOT%\start-web.ps1" (
    echo [ERROR] Web start script not found: %SCRIPT_ROOT%\start-web.ps1
    pause
    exit /b 1
)

call :start_if_missing 8000 "DevAtlas Backend - 8000" "%SCRIPT_ROOT%\start-devatlas.ps1"
timeout /t 1 /nobreak >nul

call :start_if_missing 8001 "Incident Agent Backend - 8001" "%SCRIPT_ROOT%\start-agent.ps1"
timeout /t 1 /nobreak >nul

call :start_if_missing 5174 "Incident Agent Frontend - 5174" "%SCRIPT_ROOT%\start-web.ps1"

echo Started:
echo   DevAtlas backend: http://127.0.0.1:8000
echo   Agent backend:    http://127.0.0.1:8001
echo   Agent frontend:   http://127.0.0.1:5174
echo.
echo Stop each service with Ctrl+C in its PowerShell window.
endlocal
exit /b 0

:start_if_missing
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul
if not errorlevel 1 (
    echo Port %~1 is already in use. Skipping %~2.
    exit /b 0
)
start "%~2" powershell.exe -NoLogo -NoExit -ExecutionPolicy Bypass -File "%~3"
exit /b 0
