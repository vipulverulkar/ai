@echo off
REM Pharmacy Billing App - double-click to launch (no Docker needed).
REM Usage:  start.bat         serve at http://127.0.0.1:5000
REM         start.bat 5001    serve on another port if 5000 is busy
setlocal
cd /d "%~dp0"

set PORT=%~1
if "%PORT%"=="" set PORT=5000

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python not found.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" during install^), then re-run start.bat.
  pause
  exit /b 1
)

echo [1/3] Installing Python packages...
python -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo ERROR: Could not install Python packages. Check your internet connection.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  if exist frontend\dist\index.html (
    echo [2/3] Node.js not found - serving the previously built page.
  ) else (
    echo ERROR: Node.js not found and no built page exists yet.
    echo Install Node.js LTS from https://nodejs.org/ , then re-run start.bat.
    pause
    exit /b 1
  )
) else (
  if exist frontend\dist\index.html (
    echo [2/3] Page already built - skipping. Delete the frontend\dist folder to force a rebuild.
  ) else (
    echo [2/3] Building the page - first run only, takes a few minutes...
    pushd frontend
    call npm install
    if errorlevel 1 (
      echo ERROR: Frontend install failed. Check your internet connection.
      popd
      pause
      exit /b 1
    )
    call npm run build
    if errorlevel 1 (
      echo ERROR: Frontend build failed.
      popd
      pause
      exit /b 1
    )
    popd
  )
)

echo [3/3] Starting server at http://127.0.0.1:%PORT%/  ^(login: admin / admin^)
echo Keep the "Pharmacy Server" window open while using the app. Close it to stop.
pushd backend
python -c "import waitress" >nul 2>nul
if errorlevel 1 (
  echo NOTE: waitress not available - using the Flask dev server instead.
  start "Pharmacy Server" python app.py
) else (
  start "Pharmacy Server" /min python serve.py
)
popd

timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:%PORT%/"
endlocal
exit /b 0
