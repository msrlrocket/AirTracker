@echo off
setlocal

REM Usage: flash_factory.bat COMx [baud]
REM Example: flash_factory.bat COM5 921600

if "%~1"=="" (
  echo Usage: %~n0 COMx [baud]
  echo   Example: %~n0 COM5 921600
  exit /b 1
)

set COMPORT=%~1
set BAUD=%~2
if "%BAUD%"=="" set BAUD=921600

where esptool.py >nul 2>&1
if %ERRORLEVEL%==0 (
  esptool.py --chip esp32c3 --port %COMPORT% --baud %BAUD% write_flash 0x0 factory.bin
) else (
  echo esptool.py not found on PATH, trying Python launcher...
  py -3 -m esptool --chip esp32c3 --port %COMPORT% --baud %BAUD% write_flash 0x0 factory.bin
)

endlocal

