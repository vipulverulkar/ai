@echo off
REM Stops the Clinic Management System windows started by start-windows.bat.
taskkill /FI "WINDOWTITLE eq Clinic Backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Clinic Frontend*" /T /F >nul 2>&1
echo Clinic Management System stopped.
