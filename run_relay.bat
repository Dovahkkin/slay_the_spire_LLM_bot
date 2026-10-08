@echo off
set PYTHONUTF8=1
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -u -m spire_agent.relay
) else if exist "C:\Users\yhp12\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
    "C:\Users\yhp12\AppData\Local\Python\pythoncore-3.14-64\python.exe" -u -m spire_agent.relay
) else (
    python -u -m spire_agent.relay
)
