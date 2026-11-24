@echo off
cd /d "%~dp0"
if exist "%~dp0data\twitch-runtime\websocket\__init__.py" set "PYTHONPATH=%~dp0data\twitch-runtime;%PYTHONPATH%"
if defined STREAMHELPER_PYTHON (
  "%STREAMHELPER_PYTHON%" app.py %*
  exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 app.py %*
  exit /b
)
set "STREAMHELPER_BUNDLED=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%STREAMHELPER_BUNDLED%" (
  "%STREAMHELPER_BUNDLED%" app.py %*
  exit /b
)
python app.py %*
