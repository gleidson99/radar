# Cria a tarefa "MonitorPassagens" que roda a cada hora (sem janela) enquanto o PC estiver ligado.
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe).Source }
$acao = New-ScheduledTaskAction -Execute $py -Argument "monitor_passagens.py" -WorkingDirectory $pasta
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 1)
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "MonitorPassagens" -Action $acao -Trigger $gatilho -Settings $config -Force | Out-Null
Write-Host "Tarefa criada: roda em 1 minuto e depois a cada hora. Log: log_monitor.txt"
