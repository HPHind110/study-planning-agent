@echo off
setlocal
cd /d "%~dp0"
if exist ".\runtime\python.exe" (
    ".\runtime\python.exe" -B app.py
) else (
    py -3 -B app.py
)
if errorlevel 1 pause
