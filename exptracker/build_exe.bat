@echo off
REM Build a standalone ExpenseTracker.exe (single file, includes DB logic)
pip install pyinstaller
pyinstaller --onefile --windowed --name ExpenseTracker "%~dp0expense_tracker.py"
echo.
echo EXE created in dist\ExpenseTracker.exe
echo Copy it anywhere - expenses.db will be created next to the EXE on first run.
pause
