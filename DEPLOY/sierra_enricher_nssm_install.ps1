# sierra_enricher_nssm_install.ps1 — Phase 4.2.2 install service nssm Sierra Enricher
#
# Phase 4.2.2 Sierra Full Migration (10/06/2026).
# Script PowerShell pour installer le service nssm "MIA-Sierra-Enricher-NQ"
# sur le VPS Windows. NE PAS EXECUTER en local.
#
# Prerequis VPS :
#   - nssm installe (deja present, cf reference_vps_process_persistence)
#   - Python 3.13 installe (deja present, cf project_data_v3)
#   - Fichiers MIA deployes via SCP (voir checklist)
#
# Usage VPS (Administrator) :
#   .\DEPLOY\sierra_enricher_nssm_install.ps1 -Symbol NQ
#   .\DEPLOY\sierra_enricher_nssm_install.ps1 -Symbol ES   # second instance
#
# Anti-patterns evites :
#   - Pas d'auto-start (manual confirm Jackson avant 1er start)
#   - Logs separes par symbol
#   - Rollback simple : Stop-Service + nssm remove
#
# Author : MIA Trading V2 (Phase 4.2.2 Sierra Migration)

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("ES", "NQ", "MGC")]
    [string]$Symbol,

    [string]$PythonExe = "C:/Program Files/Python311/python.exe",
    [string]$ProjectRoot = "C:/TRADING_SIERRA_CHART_AUTO",
    [string]$NssmExe = "C:/windows/system32/nssm.exe",
    [int]$PollIntervalSec = 10
)

$ServiceName = "MIA-Sierra-Enricher-$Symbol"
$WrapperScript = "$ProjectRoot/BOT/run_sierra_enricher.py"
$OutputDir = "$ProjectRoot/DATA/live_enriched/sierra"
$LogDir = "$ProjectRoot/LOGS/sierra_enricher"
$StdoutLog = "$LogDir/sierra_enricher_${Symbol}_stdout.log"
$StderrLog = "$LogDir/sierra_enricher_${Symbol}_stderr.log"

# Helper : check $LASTEXITCODE apres chaque commande nssm (fix A5 review 10/06)
function Invoke-NssmSet {
    param([string]$ServiceName, [string]$Key, [string]$Value)
    & $NssmExe set $ServiceName $Key $Value
    if ($LASTEXITCODE -ne 0) {
        Write-Error "nssm set $Key failed (exit $LASTEXITCODE)"
        exit 3
    }
}

Write-Host "=== Install nssm service : $ServiceName ===" -ForegroundColor Cyan

# 1. Verifier prerequis
if (-not (Test-Path $PythonExe)) {
    Write-Error "Python non trouve : $PythonExe"
    exit 1
}
if (-not (Test-Path $WrapperScript)) {
    Write-Error "Wrapper non trouve : $WrapperScript (SCP requis avant install)"
    exit 1
}
if (-not (Test-Path $NssmExe)) {
    Write-Error "nssm non trouve : $NssmExe"
    exit 1
}

# 2. Verifier service existant
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "WARN : Service $ServiceName existe deja. Stop + remove avant install ?" -ForegroundColor Yellow
    Write-Host "  Pour reinstaller : sierra_enricher_nssm_uninstall.ps1 -Symbol $Symbol" -ForegroundColor Yellow
    exit 2
}

# 3. Creer dirs si manquants
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# 4. Install service nssm (fix A5+B1 review : exit codes + graceful shutdown)
Write-Host "Installing service..." -ForegroundColor Green
& $NssmExe install $ServiceName $PythonExe
if ($LASTEXITCODE -ne 0) {
    Write-Error "nssm install failed (exit $LASTEXITCODE)"
    exit 3
}

# Paths quotes dans AppParameters (resilience future paths avec espaces)
$AppParams = "-X utf8 `"$WrapperScript`" --symbol $Symbol --poll-interval $PollIntervalSec --output-dir `"$OutputDir`""
Invoke-NssmSet $ServiceName AppParameters $AppParams
Invoke-NssmSet $ServiceName AppDirectory $ProjectRoot
Invoke-NssmSet $ServiceName AppStdout $StdoutLog
Invoke-NssmSet $ServiceName AppStderr $StderrLog
Invoke-NssmSet $ServiceName AppRotateFiles "1"
Invoke-NssmSet $ServiceName AppRotateBytes "10485760"  # 10 MB
Invoke-NssmSet $ServiceName Description "MIA Sierra Enricher $Symbol (Phase 4.2 dual-run Sierra Migration)"

# Manual start (Jackson confirme avant 1er start)
Invoke-NssmSet $ServiceName Start "SERVICE_DEMAND_START"

# Restart policy : restart 30s apres crash (auto-recovery propre)
# AppExit prend 2 sous-params (Default + Restart action), appel direct nssm
& $NssmExe set $ServiceName AppExit Default Restart
if ($LASTEXITCODE -ne 0) {
    Write-Error "nssm set AppExit failed (exit $LASTEXITCODE)"
    exit 3
}
Invoke-NssmSet $ServiceName AppRestartDelay "30000"

# Fix B1 review : graceful shutdown nssm
# AppStopMethodSkip=0 : utilise toutes les methodes stop (CTRL_C, CTRL_BREAK, WM_CLOSE, TerminateProcess)
# AppStopMethodConsole=5000 : 5s grace pour CTRL_BREAK (laisse wrapper Python flush via signal handler)
Invoke-NssmSet $ServiceName AppStopMethodSkip "0"
Invoke-NssmSet $ServiceName AppStopMethodConsole "5000"

Write-Host "=== Install OK ===" -ForegroundColor Green
Write-Host ""
Write-Host "Service : $ServiceName (DEMAND_START, no auto-start)" -ForegroundColor Cyan
Write-Host "Logs stdout : $StdoutLog" -ForegroundColor Cyan
Write-Host "Logs stderr : $StderrLog" -ForegroundColor Cyan
Write-Host "Output JSONL : $OutputDir/$Symbol/" -ForegroundColor Cyan
Write-Host ""
Write-Host "Pour demarrer (confirme Jackson d'abord) :" -ForegroundColor Yellow
Write-Host "  Start-Service $ServiceName" -ForegroundColor White
Write-Host ""
Write-Host "Pour status :" -ForegroundColor Yellow
Write-Host "  Get-Service $ServiceName" -ForegroundColor White
Write-Host ""
Write-Host "Pour stop :" -ForegroundColor Yellow
Write-Host "  Stop-Service $ServiceName" -ForegroundColor White
