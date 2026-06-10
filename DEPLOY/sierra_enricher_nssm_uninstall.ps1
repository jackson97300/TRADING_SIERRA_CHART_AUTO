# sierra_enricher_nssm_uninstall.ps1 — Phase 4.2.2 rollback service
#
# Rollback script : Stop + Remove service nssm "MIA-Sierra-Enricher-{Symbol}".
# Preserve les fichiers JSONL deja ecrits (DATA/live_enriched/sierra/).
#
# Usage VPS :
#   .\DEPLOY\sierra_enricher_nssm_uninstall.ps1 -Symbol NQ

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("ES", "NQ", "MGC")]
    [string]$Symbol,

    [string]$NssmExe = "C:/ProgramData/chocolatey/bin/nssm.exe"
)

$ServiceName = "MIA-Sierra-Enricher-$Symbol"

Write-Host "=== Uninstall service : $ServiceName ===" -ForegroundColor Cyan

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Service $ServiceName non trouve, rien a faire." -ForegroundColor Yellow
    exit 0
}

# Stop service (graceful si AppStopMethodConsole configure dans install.ps1)
if ($existing.Status -eq "Running") {
    Write-Host "Stopping service (graceful 5s)..." -ForegroundColor Green
    Stop-Service -Name $ServiceName -Force
    Start-Sleep -Seconds 6  # 5s grace nssm + 1s buffer
}

# Remove service (fix B2 review : check exit code)
& $NssmExe remove $ServiceName confirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "nssm remove failed (exit $LASTEXITCODE)"
    exit 3
}

Write-Host "=== Uninstall OK ===" -ForegroundColor Green
Write-Host ""
Write-Host "Fichiers preserves :" -ForegroundColor Cyan
Write-Host "  DATA/live_enriched/sierra/$Symbol/  (JSONL outputs)" -ForegroundColor White
Write-Host "  LOGS/sierra_enricher/                (logs stdout/stderr)" -ForegroundColor White
