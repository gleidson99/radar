@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH" e rode este arquivo de novo.
  pause
  exit /b 1
)
echo Instalando o Playwright (so na primeira vez)...
python -m pip install --quiet playwright
python -m playwright install chromium
echo.
python azul_sondagem.py
echo.
pause
