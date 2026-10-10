@echo off

:: 1. install dependecis
 pip install -r requirements.txt

:: 2. Run the Python program
python "run.py"

:: 3. Open the web URL
start "" "http://127.0.0.1:5000"

pause
