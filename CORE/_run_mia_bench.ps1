# Wrapper dédié mia_bench.py (2 args ES + NQ)
$logDir = "C:\TRADING_SIERRA_CHART_AUTO\_bench_logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "mia_bench_${ts}.log"
$doneFile = Join-Path $logDir "mia_bench_${ts}.done"

Set-Location "C:\TRADING_SIERRA_CHART_AUTO"
$python = "C:\Program Files\Python311\python.exe"

$start = Get-Date
"[$start] START mia_bench DATA/ES DATA/NQ" | Out-File -FilePath $logFile -Encoding utf8

& $python -X utf8 CORE\mia_bench.py "DATA/ES" "DATA/NQ" *>&1 | Out-File -FilePath $logFile -Encoding utf8 -Append
$rc = $LASTEXITCODE
$end = Get-Date
$dur = ($end - $start).TotalSeconds

"[$end] END rc=$rc duration_sec=$dur" | Out-File -FilePath $logFile -Encoding utf8 -Append

@{
    bench = "mia_bench"
    start = $start.ToString("o")
    end = $end.ToString("o")
    duration_sec = $dur
    return_code = $rc
    log_file = $logFile
} | ConvertTo-Json | Out-File -FilePath $doneFile -Encoding utf8

Write-Output "mia_bench rc=$rc duration=${dur}s log=$logFile"
exit $rc
