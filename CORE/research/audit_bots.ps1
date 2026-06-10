$LOG = 'C:\TRADING_SIERRA_CHART_AUTO\LOGS'
Write-Host "=== BOT 1 (paper) trades today ==="
$bot1 = Get-Content "$LOG\trading\trading_20260504_paper.jsonl" -ErrorAction SilentlyContinue
if ($bot1) {
    $bot1 | Select-String 'TRADE_OPEN|TRADE_CLOSE' | Select-Object -Last 5
} else {
    Write-Host "(no trading_paper.jsonl found)"
}
Write-Host ""
Write-Host "=== BOT 2 (paper_v2 NON-Bot3) trades today ==="
$paper_v2 = Get-Content "$LOG\trading\trading_20260504_paper_v2.jsonl" -ErrorAction SilentlyContinue
if ($paper_v2) {
    $paper_v2 | Where-Object { $_ -notmatch 'BOT3' -and ($_ -match 'TRADE_OPEN' -or $_ -match 'TRADE_CLOSE') } | Select-Object -Last 5
}
Write-Host ""
Write-Host "=== BOT 3 latest trades ==="
if ($paper_v2) {
    $paper_v2 | Where-Object { $_ -match 'BOT3_TRADE' } | Select-Object -Last 3
}
Write-Host ""
Write-Host "=== Sim1/2/3 positions broker NOW ==="
