@echo off
cd /d "%~dp0"
if defined STREAMHELPER_PYTHON (
  "%STREAMHELPER_PYTHON%" app.py %*
  exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 app.py %*
  exit /b
)
python app.py %*
