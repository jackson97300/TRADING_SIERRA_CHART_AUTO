# Backtest Phase B v4 - Robust Subset Rapport

Genere : DOCS\BACKTEST_PHASE_B_V4_REPORT.md
Total outcomes : 135,487

## Methodologie

- Replay 7 mois parquet v4_enriched (ES + NQ + MGC)
- 6 scenarios robust subset (features presentes dans parquet)
- 7 scenarios INERTES skipped (Phase A.3 features absentes, cf CAVEATS)
- Classification : WIN (COMPLETED/VALIDATED+r>0), LOSS (INVALIDATED), NEUTRAL (EXPIRED)
- hit_rate = WIN / (WIN + LOSS) [exclut neutrals]

## Hit Rate par Scenario

| Scenario | N | Wins | Losses | Hit Rate | R median | R mean | MFE | MAE | Cap actuel |
|---|---|---|---|---|---|---|---|---|---|
| VWAP SD3 Touch Reversal SHORT | 2594 | 997 | 299 | 76.93% | -0.0 | -0.022 | 0.234 | -0.214 | 65 |
| VWAP SD3 Touch Reversal LONG | 2239 | 732 | 307 | 70.45% | 0.0 | -0.034 | 0.281 | -0.241 | 65 |
| Bearish rejection | 17398 | 3132 | 1835 | 63.06% | -0.0 | 0.046 | 0.707 | -0.083 | 70 |
| Bullish continuation | 15931 | 2710 | 2165 | 55.59% | 0.0 | -0.002 | 0.463 | -0.189 | 65 |
| Range bound SHORT fade | 17373 | 1468 | 2990 | 32.93% | -0.0 | -0.089 | 0.813 | -0.16 | 50 |
| Range bound LONG fade | 20972 | 1668 | 4087 | 28.98% | 0.0 | -0.116 | 0.726 | -0.198 | 50 |
| VWAP SD2 Touch Reversal SHORT | 14317 | 430 | 3114 | 12.13% | -0.0 | -0.193 | 0.167 | -0.146 | 55 |
| VWAP SD2 Touch Reversal LONG | 12377 | 449 | 3515 | 11.33% | 0.0 | -0.252 | 0.19 | -0.174 | 55 |
| IB Break Continuation LONG (Dalton) | 17571 | 7 | 2726 | 0.26% | 0.0 | -0.155 | 0.285 | -0.308 | 70 |
| IB Break Continuation SHORT (Dalton) | 14715 | 0 | 2066 | 0.0% | -0.0 | -0.14 | 0.295 | -0.296 | 70 |

## Hit Rate par Scenario x Regime VIX

| Scenario | Regime | N | Hit Rate | R median |
|---|---|---|---|---|
| Bearish rejection | calm | 2660 | 45.83% | -0.0 |
| Bearish rejection | elevated | 14566 | 66.98% | -0.0 |
| Bearish rejection | stressed | 172 | 46.67% | -0.0 |
| Bullish continuation | calm | 2332 | 33.63% | 0.0 |
| Bullish continuation | elevated | 13562 | 60.67% | 0.0 |
| Bullish continuation | stressed | 37 | 23.08% | 0.0 |
| IB Break Continuation LONG (Dalton) | calm | 3181 | 0.0% | 0.0 |
| IB Break Continuation LONG (Dalton) | elevated | 14277 | 0.0% | 0.0 |
| IB Break Continuation LONG (Dalton) | stressed | 113 | 46.67% | 0.0 |
| IB Break Continuation SHORT (Dalton) | calm | 2751 | 0.0% | -0.0 |
| IB Break Continuation SHORT (Dalton) | elevated | 11818 | 0.0% | -0.0 |
| IB Break Continuation SHORT (Dalton) | stressed | 146 | 0.0% | -0.0 |
| Range bound LONG fade | calm | 3538 | 25.63% | 0.0 |
| Range bound LONG fade | elevated | 17434 | 30.02% | 0.0 |
| Range bound SHORT fade | calm | 2744 | 25.1% | -0.0 |
| Range bound SHORT fade | elevated | 14629 | 35.14% | -0.0 |
| VWAP SD2 Touch Reversal LONG | calm | 2233 | 3.15% | 0.0 |
| VWAP SD2 Touch Reversal LONG | elevated | 10024 | 14.73% | 0.0 |
| VWAP SD2 Touch Reversal LONG | stressed | 120 | 2.04% | 0.0 |
| VWAP SD2 Touch Reversal SHORT | calm | 1812 | 3.76% | -0.0 |
| VWAP SD2 Touch Reversal SHORT | elevated | 12342 | 15.0% | -0.0 |
| VWAP SD2 Touch Reversal SHORT | stressed | 163 | 2.74% | -0.0 |
| VWAP SD3 Touch Reversal LONG | calm | 275 | 41.04% | 0.0 |
| VWAP SD3 Touch Reversal LONG | elevated | 1954 | 74.58% | 0.0 |
| VWAP SD3 Touch Reversal LONG | stressed | 10 | 100.0% | 0.222 |
| VWAP SD3 Touch Reversal SHORT | calm | 186 | 64.34% | -0.0 |
| VWAP SD3 Touch Reversal SHORT | elevated | 2394 | 78.29% | -0.0 |
| VWAP SD3 Touch Reversal SHORT | stressed | 14 | 83.33% | -0.0 |

## Hit Rate par Scenario x Setup Type

| Scenario | Setup | N | Hit Rate | R median |
|---|---|---|---|---|
| Bearish rejection | swing | 17398 | 63.06% | -0.0 |
| Bullish continuation | swing | 15931 | 55.59% | 0.0 |
| IB Break Continuation LONG (Dalton) | swing | 17571 | 0.26% | 0.0 |
| IB Break Continuation SHORT (Dalton) | swing | 14715 | 0.0% | -0.0 |
| Range bound LONG fade | swing | 20972 | 28.98% | 0.0 |
| Range bound SHORT fade | swing | 17373 | 32.93% | -0.0 |
| VWAP SD2 Touch Reversal LONG | scalp | 12377 | 11.33% | 0.0 |
| VWAP SD2 Touch Reversal SHORT | scalp | 14317 | 12.13% | -0.0 |
| VWAP SD3 Touch Reversal LONG | swing | 2239 | 70.45% | 0.0 |
| VWAP SD3 Touch Reversal SHORT | swing | 2594 | 76.93% | -0.0 |

## Recommandations Cap Recalibration

Reference Lopez AFML ch.13 : si hit_rate_empirical >> cap heuristic_score,
le scenario est sous-calibre (manque opportunites). Si <<, sur-calibre (faux signaux).

- **Range bound SHORT fade** : hit_rate=32.93% vs cap=50 (-17.1) -> SUR-CALIBRE (lower cap)
- **Range bound LONG fade** : hit_rate=28.98% vs cap=50 (-21.0) -> SUR-CALIBRE (lower cap)
- **VWAP SD2 Touch Reversal SHORT** : hit_rate=12.13% vs cap=55 (-42.9) -> SUR-CALIBRE (lower cap)
- **VWAP SD2 Touch Reversal LONG** : hit_rate=11.33% vs cap=55 (-43.7) -> SUR-CALIBRE (lower cap)
- **IB Break Continuation LONG (Dalton)** : hit_rate=0.26% vs cap=70 (-69.7) -> SUR-CALIBRE (lower cap)
- **IB Break Continuation SHORT (Dalton)** : hit_rate=0.0% vs cap=70 (-70.0) -> SUR-CALIBRE (lower cap)
