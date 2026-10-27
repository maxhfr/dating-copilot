@echo off
rem Windows launcher.   run.bat swipe [platform]   |   run.bat app
cd /d "%~dp0"
call .venv\Scripts\activate.bat
if /i "%~1"=="app" (
  python src\gui.py
) else (
  python src\cli.py %2
)
