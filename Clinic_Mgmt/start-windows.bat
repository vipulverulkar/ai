@echo off
REM =====================================================================
REM  Clinic Management System - standalone launcher for Windows (no Docker)
REM  Double-click this file. It will:
REM    1. Check for Python 3.8+ and Node.js 18+ (auto-install via winget
REM       if missing - needs internet on first run)
REM    2. Create backend\venv, install Python + Node dependencies
REM    3. Start backend (port 5001) and frontend (port 3000) in their own
REM       windows, then open http://localhost:3000 in your browser
REM  Stop everything with stop-windows.bat (or just close both windows).
REM  Override defaults:  set API_KEY=... ^& set ADMIN_PASSWORD=... ^& start-windows.bat
REM =====================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set BACKEND_PORT=%PORT%
if not defined BACKEND_PORT set BACKEND_PORT=5001
if not defined FRONTEND_PORT set FRONTEND_PORT=3000
if not defined FLASK_API set FLASK_API=http://localhost:%BACKEND_PORT%/api

REM ---- 1. Python 3.8+ -------------------------------------------------
set PYTHON=
where py >nul 2>&1 && set PYTHON=py -3
if not defined PYTHON (
  where python >nul 2>&1 && set PYTHON=python
)
if not defined PYTHON (
  echo Python not found. Trying to install via winget...
  call :winget_install "Python.Python.3.11" || goto :missing_python
  where py >nul 2>&1 && set PYTHON=py -3
  if not defined PYTHON (
    where python >nul 2>&1 && set PYTHON=python
  )
  REM Fresh installs may not be on PATH yet in this session - check well-known locations
  if not defined PYTHON (
    for /d %%d in ("%LocalAppData%\Programs\Python\Python3*") do if exist "%%d\python.exe" set PYTHON="%%d\python.exe"
  )
)
if not defined PYTHON goto :missing_python
for /f "tokens=1,2 delims=." %%a in ('%PYTHON% -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"') do (
  set PY_MAJOR=%%a & set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 goto :missing_python
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 8 goto :missing_python
echo [OK] Python %PY_MAJOR%.%PY_MINOR% ^(%PYTHON%^)

REM ---- 2. Node.js 18+ --------------------------------------------------
where node >nul 2>&1
if errorlevel 1 (
  echo Node.js not found. Trying to install via winget...
  call :winget_install "OpenJS.NodeJS.LTS" || goto :missing_node
  if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%ProgramFiles%\nodejs;!PATH!"
)
for /f "tokens=2 delims=v." %%v in ('node --version 2^>nul') do set NODE_MAJOR=%%v
if not defined NODE_MAJOR goto :missing_node
if %NODE_MAJOR% LSS 18 (
  echo ERROR: Node.js 18+ required, found %NODE_MAJOR%. Update via: winget upgrade OpenJS.NodeJS.LTS
  pause & exit /b 1
)
echo [OK] Node.js v%NODE_MAJOR%.x

REM ---- 3. Shared secrets ------------------------------------------------
if not defined API_KEY set API_KEY=dev-key
if "%API_KEY%"=="dev-key" echo WARNING: using default dev API key. Set API_KEY env var in production.
set FLASK_API_KEY=%API_KEY%
if not exist ".session_secret" (
  %PYTHON% -c "import secrets; print(secrets.token_hex(32))" > .session_secret
)
set /p SESSION_SECRET=<.session_secret

REM ---- 4. Backend --------------------------------------------------------
if not exist "backend\venv" (
  echo Creating Python virtual environment...
  %PYTHON% -m venv backend\venv || (echo ERROR: could not create venv. Try: %PYTHON% -m pip install virtualenv & pause & exit /b 1)
)
echo Installing Python dependencies...
backend\venv\Scripts\python -m pip install -r backend\requirements.txt >nul 2>&1
echo Starting Flask backend on port %BACKEND_PORT%...
set PORT=%BACKEND_PORT%
set FLASK_DEBUG=1
start "Clinic Backend" cmd /c "cd /d ""%~dp0backend"" && venv\Scripts\python app.py"

REM ---- 5. Frontend -------------------------------------------------------
if not exist "frontend\node_modules" (
  echo Installing Node.js dependencies...
  pushd frontend && call npm install >nul 2>&1 & popd
)
echo Starting Node.js frontend on port %FRONTEND_PORT%...
set PORT=%FRONTEND_PORT%
start "Clinic Frontend" cmd /c "cd /d ""%~dp0frontend"" && npm start"

REM ---- 6. Open browser once the frontend answers -------------------------
echo Waiting for the app to come up...
for /l %%i in (1,1,30) do (
  curl -sf http://localhost:%FRONTEND_PORT%/health >nul 2>&1
  if not errorlevel 1 goto :open_browser
  timeout /t 2 /nobreak >nul
)
echo WARNING: frontend did not answer within 60s - check the "Clinic Frontend" window for errors.
pause & exit /b 1

:open_browser
echo.
echo ==========================================
echo  Clinic Management System is running!
echo ==========================================
echo  Frontend:    http://localhost:%FRONTEND_PORT%
echo  Backend API: http://localhost:%BACKEND_PORT%/api
echo.
echo  Default login: admin / admin123
echo  (override first-run admin via ADMIN_USERNAME / ADMIN_PASSWORD)
echo.
echo  Stop everything with stop-windows.bat
echo  (or close the Clinic Backend / Clinic Frontend windows)
start http://localhost:%FRONTEND_PORT%/
exit /b 0

:winget_install
where winget >nul 2>&1
if errorlevel 1 (
  echo ERROR: winget not found - install %~1 manually from https://winget.run or the Microsoft Store.
  exit /b 1
)
winget install -e --id %~1 --silent --accept-package-agreements --accept-source-agreements
exit /b %errorlevel%

:missing_python
echo ERROR: Python 3.8+ is required. Install it from https://www.python.org/downloads/
echo        ^(tick "Add python.exe to PATH"^) or run: winget install Python.Python.3.11
pause & exit /b 1

:missing_node
echo ERROR: Node.js 18+ is required. Install it from https://nodejs.org/
echo        or run: winget install OpenJS.NodeJS.LTS
pause & exit /b 1
