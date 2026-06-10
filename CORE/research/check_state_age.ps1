$now = Get-Date
$file = (Get-ChildItem 'C:\TRADING_SIERRA_CHART_AUTO\DATA\PAPER_TRADES\databento_paper_v2_state.json').LastWriteTime
$file3 = (Get-ChildItem 'C:\TRADING_SIERRA_CHART_AUTO\DATA\PAPER_TRADES\databento_paper_v3_state.json').LastWriteTime
Write-Host "NOW: $now"
Write-Host "FILE V2: $file (age $([Math]::Round(($now - $file).TotalSeconds, 0))s)"
Write-Host "FILE V3: $file3 (age $([Math]::Round(($now - $file3).TotalSeconds, 0))s)"
