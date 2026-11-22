# Phase 8 S2h: register the Strata startup task on Zeus (run once, on Zeus).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File eval\zeus_strata_task.ps1 [-Unregister]
#
# The task "Palimnesis Strata" starts Strata at boot with the D115.12 command and config
# (temperature 1.0 / 0.95 / 20, 32K, one slot): never `strata launch`, which rewrites the
# config's sampling to 0.6. S4U logon runs it whether or not anyone is logged on and stores
# no password. Output goes to iq3_xxs-32k-t1.out beside the config. It does not start Strata
# now; `eval/run_ready.py` checks that the task exists, and the headless runner waits for
# /props after every boot (about 16 minutes of loading).
param([switch]$Unregister)
$ErrorActionPreference = 'Stop'
$name = 'Palimnesis Strata'
if ($Unregister) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
$dir = 'E:\Strata-0.2.11\terminal\0.1.58'
$py = Join-Path $dir 'python\python.exe'
$config = Join-Path $env:LOCALAPPDATA 'Strata\launch\iq3_xxs-32k-t1.json'
$log = Join-Path $env:LOCALAPPDATA 'Strata\launch\iq3_xxs-32k-t1.out'
foreach ($p in @($py, $config)) { if (-not (Test-Path $p)) { throw "missing $p" } }
$cfg = Get-Content $config -Raw | ConvertFrom-Json
if ($cfg.sampling.temperature -ne 1.0) { throw "$config has temperature $($cfg.sampling.temperature), expected 1.0" }
$cmd = "`"$py`" -m serve.server --engine strata --config `"$config`" --host 0.0.0.0 --port 8080 --parallel 1 --no-api-key >> `"$log`" 2>&1"
$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c $cmd" -WorkingDirectory $dir
$t = New-ScheduledTaskTrigger -AtStartup
$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$s = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit 0 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
"registered $name"
