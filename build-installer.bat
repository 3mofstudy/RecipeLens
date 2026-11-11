@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build.ps1
echo.
if errorlevel 1 (echo BUILD FAILED - please screenshot this window.) else (echo BUILD OK - installer is in dist\installer)
start "" "%~dp0dist\installer"
pause
