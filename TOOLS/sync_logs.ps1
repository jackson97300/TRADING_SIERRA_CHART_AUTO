# sync_logs.ps1 - Sync VPS LOGS -> local toutes 5 min via robocopy SSH/SCP
# Cree 25/06/2026 (Jackson) - Option B INCIDENT_LOG #87 SYNC_MISS fix
#
# Usage manuel: powershell.exe -ExecutionPolicy Bypass -File D:\TRADING_SIERRA_CHART_AUTO\tools\sync_logs.ps1
# Usage tache planifiee Windows: trigger 5 min, action = ce script
#
# Pourquoi pas hook Claude SessionStart : INCIDENT_LOG mai 2026 - MCP handshake
# timeout 30s = Claude Code injouable si scp dans hook. Option B = sync externe.

$ErrorActionPreference = "SilentlyContinue"

$VPS_USER = "Administrator"
$VPS_HOST = "212.28.179.199"
$VPS_LOGS = "C:/TRADING_SIERRA_CHART_AUTO/LOGS"
$LOCAL_LOGS = "D:/TRADING_SIERRA_CHART_AUTO/LOGS"
$LOG_FILE = "D:/TRADING_SIERRA_CHART_AUTO/tools/sync_logs.log"

# Dirs critiques a sync (limites pour rapidite - on ne sync pas TOUT LOGS/)
$DIRS = @(
    "decisions",
    "events",
    "execution",
    "errors",
    "risk",
    "trading",
    "bot_mr_decisions",
    "bot_bn_v4_decisions"
)

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LOG_FILE -Value "[$ts] sync_logs START"

$totalFiles = 0
$errors = 0

foreach ($dir in $DIRS) {
    $vpsPath = "${VPS_USER}@${VPS_HOST}:${VPS_LOGS}/${dir}/*.jsonl"
    $localPath = "${LOCAL_LOGS}/${dir}/"

    if (-not (Test-Path $localPath)) {
        New-Item -ItemType Directory -Path $localPath -Force | Out-Null
    }

    # SCP en mode -p (preserve mtime). -q quiet.
    # Note : Windows SCP n'a pas l'option --update, donc on copie inconditionnel.
    # Acceptable car JSONL append-only (LastWrite VPS > local = besoin copy).
    & scp -q -p $vpsPath $localPath 2>$null

    if ($LASTEXITCODE -eq 0) {
        $count = (Get-ChildItem "${LOCAL_LOGS}/${dir}/*.jsonl" -ErrorAction SilentlyContinue).Count
        $totalFiles += $count
    } else {
        $errors++
        Add-Content -Path $LOG_FILE -Value "[$ts] WARN: scp $dir exit=$LASTEXITCODE"
    }
}

$ts_end = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LOG_FILE -Value "[$ts_end] sync_logs END files=$totalFiles errors=$errors"

# Rotation log : garder dernier 1000 lignes
$content = Get-Content $LOG_FILE -ErrorAction SilentlyContinue
if ($content -and $content.Count -gt 1000) {
    $content | Select-Object -Last 800 | Set-Content $LOG_FILE
}
