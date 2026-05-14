@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File .\start_microservices.ps1
pause
