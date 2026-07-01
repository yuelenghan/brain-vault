@echo off
setlocal
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "%~dpn0" %*
  exit /b %ERRORLEVEL%
)
python "%~dpn0" %*
exit /b %ERRORLEVEL%
