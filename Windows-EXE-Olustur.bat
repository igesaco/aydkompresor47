@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-windows.ps1"
if errorlevel 1 (
 echo.
 echo Paketleme tamamlanamadi. Yukaridaki hata mesajini kontrol edin.
 pause
 exit /b 1
)
echo.
echo EXE hazir: dist\AYD-Kompresor.exe
pause
