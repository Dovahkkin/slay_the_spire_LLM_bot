@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -u "%~dp0main.py" --driver live
) else if exist "C:\Users\yhp12\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
    "C:\Users\yhp12\AppData\Local\Python\pythoncore-3.14-64\python.exe" -u "%~dp0main.py" --driver live
) else (
    python -u "%~dp0main.py" --driver live
)
