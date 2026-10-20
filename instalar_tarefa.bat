@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0instalar_tarefa.ps1"
pause
