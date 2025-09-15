@echo off
setlocal

REM Usage: erase_flash.bat COMx
REM Example: erase_flash.bat COM5

if "%~1"=="" (
  echo Usage: %~n0 COMx
  echo   Example: %~n0 COM5
  exit /b 1
)

set COMPORT=%~1

where esptool.py >nul 2>&1
if %ERRORLEVEL%==0 (
  esptool.py --chip esp32c3 --port %COMPORT% erase_flash
) else (
  echo esptool.py not found on PATH, trying Python launcher...
  py -3 -m esptool --chip esp32c3 --port %COMPORT% erase_flash
)

endlocal

