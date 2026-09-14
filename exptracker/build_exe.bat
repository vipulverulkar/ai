@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Build ExpenseTracker.exe

REM ============================================================
REM  Build a standalone ExpenseTracker.exe (Windows)
REM  - Auto-detects Python (python / py / python3)
REM  - Auto-installs requirements.txt + PyInstaller
REM  - Produces dist\ExpenseTracker.exe (single-file, windowed)
REM  - DB (expenses.db) is created BESIDE the EXE on first run
REM ============================================================

echo ============================================================
echo   Build ExpenseTracker.exe — PyInstaller
echo ============================================================
echo.

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

REM -- find Python --
set "PY="
where python >nul 2>&1 && set "PY=python" && goto :foundpy
where py >nul 2>&1 && set "PY=py -3" && goto :foundpy
where python3 >nul 2>&1 && set "PY=python3" && goto :foundpy

:foundpy
if "%PY%"=="" (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/  (check "Add to PATH")
    pause
    exit /b 1
)
echo [1/4] Python: 
%PY% --version
if errorlevel 1 ( echo [ERROR] Python failed & pause & exit /b 1 )
echo.

REM -- ensure pip --
%PY% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] pip not found, running ensurepip...
    %PY% -m ensurepip --upgrade
)
echo [2/4] Upgrading pip...
%PY% -m pip install --upgrade pip
echo.

REM -- install requirements.txt (if present) --
if exist "%ROOT%\requirements.txt" (
    echo [3/4] Installing requirements.txt ...
    %PY% -m pip install -r "%ROOT%\requirements.txt"
    if errorlevel 1 (
        echo [WARN] requirements install had issues — continuing.
    ) else (
        echo        Done.
    )
) else (
    echo [3/4] No requirements.txt — skipping.
)
echo.

REM -- ensure PyInstaller --
echo        Ensuring PyInstaller is installed...
%PY% -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    %PY% -m pip install pyinstaller
    if errorlevel 1 ( echo [ERROR] Failed to install PyInstaller & pause & exit /b 1 )
) else (
    echo        PyInstaller already installed.
)
%PY% -m PyInstaller --version
echo.

REM -- build --
echo [4/4] Building EXE with PyInstaller (this may take 30-60s)...
echo        Command: pyinstaller --onefile --windowed --name ExpenseTracker "%ROOT%\expense_tracker.py"
echo.
%PY% -m PyInstaller --onefile --windowed --name ExpenseTracker --clean --noconfirm "%ROOT%\expense_tracker.py"
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. See log above.
    echo Try:  %PY% -m pip install --upgrade pyinstaller ^&^& %PY% -m PyInstaller --onefile --windowed --name ExpenseTracker expense_tracker.py
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Build succeeded!
echo  EXE: %ROOT%\dist\ExpenseTracker.exe
echo  Size:
dir "%ROOT%\dist\ExpenseTracker.exe" | findstr /i "ExpenseTracker.exe"
echo.
echo  Copy the EXE anywhere — on first run it will create
echo  expenses.db BESIDE the EXE (portable, like .accdb).
echo  To back up, just copy expenses.db.
echo ============================================================
echo.

REM -- optional: open dist folder --
if exist "%ROOT%\dist\ExpenseTracker.exe" (
    echo Opening dist folder...
    explorer "%ROOT%\dist"
)

pause
endlocal
