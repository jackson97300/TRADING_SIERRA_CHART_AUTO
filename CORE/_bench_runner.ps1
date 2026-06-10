param(
    [Parameter(Mandatory=$true)][string]$BenchName,
    [Parameter(Mandatory=$true)][string]$Script,
    [string[]]$ScriptArgs = @()
)

# Cree repertoire log
$logDir = "C:\TRADING_SIERRA_CHART_AUTO\_bench_logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "${BenchName}_${ts}.log"
$doneFile = Join-Path $logDir "${BenchName}_${ts}.done"

Set-Location "C:\TRADING_SIERRA_CHART_AUTO"
$python = "C:\Program Files\Python311\python.exe"

$start = Get-Date
"[$start] START bench=$BenchName script=$Script args=$($ScriptArgs -join ' ')" | Out-File -FilePath $logFile -Encoding utf8

# Build args list
$allArgs = @("-X", "utf8", $Script) + $ScriptArgs

# Run with stdout+stderr to log
& $python $allArgs *>&1 | Out-File -FilePath $logFile -Encoding utf8 -Append
$rc = $LASTEXITCODE
$end = Get-Date
$dur = ($end - $start).TotalSeconds

"[$end] END bench=$BenchName rc=$rc duration_sec=$dur" | Out-File -FilePath $logFile -Encoding utf8 -Append

# Marker done file with metadata
@{
    bench = $BenchName
    script = $Script
    args = $ScriptArgs
    start = $start.ToString("o")
    end = $end.ToString("o")
    duration_sec = $dur
    return_code = $rc
    log_file = $logFile
} | ConvertTo-Json | Out-File -FilePath $doneFile -Encoding utf8

Write-Output "$BenchName completed rc=$rc duration=${dur}s log=$logFile"
exit $rc
