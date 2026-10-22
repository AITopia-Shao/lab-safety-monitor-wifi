@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
"%~dp0labguard\.runtime\python\python.exe" "%~dp0connect_android.py"
pause
