param([int]$MaxSeconds = 360)
$log = "C:\TRADING_SIERRA_CHART_AUTO\LOGS\live_pipeline_loop.log"
$start = Get-Date
$found = $null
while (((New-TimeSpan -Start $start).TotalSeconds) -lt $MaxSeconds) {
    $tail = Get-Content $log -Tail 5 -ErrorAction SilentlyContinue
    if ($tail) {
        foreach ($line in $tail) {
            if ($line -match "iter 1 OK") {
                $found = "OK: $line"
                break
            }
            if ($line -match "iter 1 FAIL") {
                $found = "FAIL: $line"
                break
            }
        }
    }
    if ($found) { break }
    Start-Sleep -Seconds 15
}
if ($found) { Write-Output $found } else { Write-Output "TIMEOUT after $MaxSeconds seconds" }
Write-Output "--- tail 25 ---"
Get-Content $log -Tail 25
