$now = Get-Date
Write-Host "=== LIVE_CACHE diag ==="
Get-ChildItem 'C:\TRADING_SIERRA_CHART_AUTO\DATA\LIVE_CACHE\' | ForEach-Object {
    $age = [Math]::Round(($now - $_.LastWriteTime).TotalSeconds, 0)
    Write-Host "  $($_.Name) age=${age}s"
}
Write-Host ""
Write-Host "=== MIA-Live-OHLCV service ==="
Get-Service MIA-Live-OHLCV | Format-List Name,Status
Write-Host "=== databento_live_stream.log tail ==="
$log = 'C:\TRADING_SIERRA_CHART_AUTO\DATA\LOGS\databento_live_stream.log'
if (Test-Path $log) {
    Get-Content $log -Tail 15
} else {
    Write-Host "(log absent)"
}
