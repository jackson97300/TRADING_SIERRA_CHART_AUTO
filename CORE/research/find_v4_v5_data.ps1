Write-Host "=== Repertoires DATA ==="
Get-ChildItem 'C:\TRADING_SIERRA_CHART_AUTO\DATA\' -Directory | Select-Object Name,LastWriteTime | Format-Table -AutoSize

Write-Host ""
Write-Host "=== Tous les .parquet recents (top 20) ==="
Get-ChildItem 'C:\TRADING_SIERRA_CHART_AUTO\DATA\' -Filter '*.parquet' -Recurse -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 20 |
    ForEach-Object {
        $rel = $_.FullName.Replace('C:\TRADING_SIERRA_CHART_AUTO\DATA\','')
        $size = [Math]::Round($_.Length/1MB, 2)
        Write-Host "  $rel ($size MB) $($_.LastWriteTime)"
    }

Write-Host ""
Write-Host "=== Repertoires lies a v4/v5/enriched (recursive) ==="
Get-ChildItem 'C:\TRADING_SIERRA_CHART_AUTO\' -Directory -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'v4|v5|enriched|datasets|paper_v4|paper_v5' } |
    Select-Object FullName,LastWriteTime |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== Fichiers parquet portant v4 ou v5 ==="
Get-ChildItem 'C:\TRADING_SIERRA_CHART_AUTO\' -Filter '*.parquet' -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'v4|v5|enrich' -or $_.Directory.Name -match 'v4|v5|enrich' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 15 |
    ForEach-Object {
        $rel = $_.FullName.Replace('C:\TRADING_SIERRA_CHART_AUTO\','')
        $size = [Math]::Round($_.Length/1MB, 2)
        Write-Host "  $rel ($size MB) $($_.LastWriteTime)"
    }
