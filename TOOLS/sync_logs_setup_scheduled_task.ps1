# sync_logs_setup_scheduled_task.ps1 - Setup tache planifiee Windows
# Lance UNE FOIS en admin pour creer la tache "MIA-Sync-Logs-VPS" (5 min).
#
# Usage admin :
#   powershell.exe -ExecutionPolicy Bypass -File D:\TRADING_SIERRA_CHART_AUTO\tools\sync_logs_setup_scheduled_task.ps1
#
# Suppression :
#   Unregister-ScheduledTask -TaskName "MIA-Sync-Logs-VPS" -Confirm:$false

$TaskName = "MIA-Sync-Logs-VPS"
$ScriptPath = "D:\TRADING_SIERRA_CHART_AUTO\tools\sync_logs.ps1"

# Verifier admin
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERREUR : ce script doit etre lance en ADMINISTRATEUR." -ForegroundColor Red
    exit 1
}

# Supprimer tache existante si presente
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Tache existante trouvee. Suppression..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action : powershell.exe -File <script>
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

# Trigger : toutes 5 min, repeat infini
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 365)

# Settings : silencieux + restart on fail + cap 4 min execution
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Principal : utilisateur courant + NIVEAU LE PLUS HAUT pour acces network drive
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# Registrer
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Sync VPS LOGS toutes 5 min vers local (INCIDENT_LOG #87 fix)"

Write-Host "Tache '$TaskName' creee avec succes." -ForegroundColor Green
Write-Host "Trigger : toutes 5 min." -ForegroundColor Cyan
Write-Host "Script  : $ScriptPath" -ForegroundColor Cyan
Write-Host "Log     : D:\TRADING_SIERRA_CHART_AUTO\tools\sync_logs.log" -ForegroundColor Cyan
Write-Host ""
Write-Host "Suppression : Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Yellow
