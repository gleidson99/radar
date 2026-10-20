@echo off
cd /d "%~dp0"
echo Teste do monitor (abre o Chrome visivel, nao grava historico)...
set TESTE=1
set VER_JANELA=1
set MODO=completo
set MAX_BUSCAS=4
python monitor_passagens.py
echo.
echo Fim do teste. Veja se chegou mensagem no Telegram.
pause
