@echo off
powershell -Command "Unregister-ScheduledTask -TaskName MonitorPassagens -Confirm:$false"
pause
