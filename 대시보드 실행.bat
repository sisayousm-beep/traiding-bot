@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONWARNINGS=ignore
title QuantBot Dashboard
cd /d "%~dp0"
echo ============================================
echo   QuantBot Dashboard
echo   The browser will open automatically.
echo   Close this window (or Ctrl+C) to stop.
echo ============================================
echo.
python -m webapp.server --open
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to start. Is Python installed and on PATH?
  echo Try: pip install -r requirements.txt
)
echo.
echo Server stopped.
pause
