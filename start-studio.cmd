@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\trade-studio.exe" (
  echo Trade Router Studio is not installed in this folder.
  pause
  exit /b 1
)

".venv\Scripts\trade-studio.exe" start %*
if errorlevel 1 (
  echo.
  echo Trade Router Studio failed to start.
  pause
  exit /b 1
)

endlocal
