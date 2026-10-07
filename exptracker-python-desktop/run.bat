@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Daily Expense Tracker

REM ============================================================
REM  Daily Expense Tracker — One-click launcher (Windows)
REM  - Auto-detects Python (python / py / python3)
REM  - Auto-installs requirements.txt if present
REM  - Launches the app (expense_tracker.py)
REM ============================================================

echo ============================================================
echo   Daily Expense Tracker — Launcher
echo ============================================================
echo.

REM -- locate project dir (where this .bat lives) --
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM -- find Python --
set "PY="
where python >nul 2>&1 && set "PY=python" && goto :foundpy
where py >nul 2>&1 && set "PY=py -3" && goto :foundpy
where python3 >nul 2>&1 && set "PY=python3" && goto :foundpy

:foundpy
if "%PY%"=="" (
    echo [ERROR] Python not found in PATH.
    echo.
    echo  Please install Python 3.10+ from https://www.python.org/downloads/
    echo  IMPORTANT: check "Add python.exe to PATH" and "tcl/tk and IDLE" during install.
    echo.
    pause
    exit /b 1
)

echo [1/3] Python found: 
%PY% --version
if errorlevel 1 (
    echo [ERROR] Failed to run Python.
    pause
    exit /b 1
)
echo.

REM -- check tkinter (stdlib) --
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [WARN] tkinter not available. Reinstall Python with "tcl/tk and IDLE" checked.
    echo        Or run:  pip install tk  (not sufficient) — you need the system Tk.
    echo.
)

REM -- install requirements (if file exists) --
if exist "%ROOT%\requirements.txt" (
    echo [2/3] Installing requirements from requirements.txt ...
    %PY% -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo [INFO] pip not found, trying ensurepip...
        %PY% -m ensurepip --upgrade >nul 2>&1
    )
    echo        Upgrading pip...
    %PY% -m pip install --upgrade pip >nul 2>&1
    echo        Installing -r requirements.txt ...
    %PY% -m pip install -r "%ROOT%\requirements.txt"
    if errorlevel 1 (
        echo [WARN] pip install had warnings/errors — continuing anyway.
        echo        See above. The app itself needs no pip packages to run.
    ) else (
        echo        Requirements installed (or already satisfied).
    )
) else (
    echo [2/3] No requirements.txt found — skipping pip install.
    echo        (App runs on stdlib only: tkinter + sqlite3)
)
echo.

REM -- launch app --
echo [3/3] Launching Daily Expense Tracker...
echo        DB will be created as: %ROOT%\expenses.db  (portable, copy to back up)
echo        Log: no log file — close window to exit.
echo.
%PY% "%ROOT%\expense_tracker.py"
set "EXITCODE=%ERRORLEVEL%"
echo.
if "%EXITCODE%"=="0" (
    echo App exited normally.
) else (
    echo [ERROR] App exited with code %EXITCODE%.
    echo If you saw "No module named 'tkinter'":
    echo   - Reinstall Python with "tcl/tk and IDLE" checked, or
    echo   - On Windows Store Python, install from python.org instead.
)

echo.
pause
endlocal
exit /b %EXITCODE%
