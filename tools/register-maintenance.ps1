param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskName = 'DevPLM Private Maintenance'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$statePath = Join-Path $projectRoot '.local\stack.json'
if (-not (Test-Path -LiteralPath $statePath)) { throw 'Initialize this private stack first.' }
$stack = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$pythonPath = [System.IO.Path]::GetFullPath($stack.python)
$pythonwPath = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) { throw 'Existing windowless Python runtime not found.' }
$scriptPath = Join-Path $projectRoot 'tools\maintenance.py'
$arguments = '"' + $scriptPath + '" cycle'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Actions.Count -ne 1 -or $existing.Actions[0].Execute -ne $pythonwPath -or $existing.Actions[0].Arguments -ne $arguments) {
        throw 'Existing task differs; refusing to replace another task.'
    }
    if ($Remove) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false; Write-Output '{"removed":true}'; exit 0 }
    Write-Output '{"configured":true,"existing":true}'; exit 0
}
if ($Remove) { Write-Output '{"removed":false}'; exit 0 }
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonwPath -Argument $arguments -WorkingDirectory $projectRoot
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon,$repeat) -Principal $principal -Settings $settings -Description 'Recover the owned dev-plm private stack; daily local backup and isolated restore verification. No public exposure.' | Out-Null
Write-Output '{"configured":true,"every_minutes":5,"backup":"daily with restore verification","runs":"while user logged in"}'
