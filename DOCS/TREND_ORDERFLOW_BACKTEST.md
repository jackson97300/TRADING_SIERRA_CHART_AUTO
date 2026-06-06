# Backtest variantes trend_orderflow_alignment_20b

**Date** : 2026-06-07
**Symbole** : NQ
**Jours testes** : 81 (live_enriched)
**Bars RTH median** : 385
**Label** : direction forward 5 bars (close[t+5] - close[t])

## Variantes testees

**Direction tendance** :
- T1 : `(close - close[-20]) / atr_daily` — pur prix normalise ATR
- T2 : `vwap_slope_10` Sierra (slope 1h30)
- T3 : `(T1 + T2) / 2` — combo

**Orderflow cumul 20b** :
- O1 : `mean(delta_bar[-20:])` flat
- O2 : `EMA(delta_bar, span=20)` exponentiel
- O3 : `(n_big_ask_t1 - n_big_bid_t1).rolling(20).mean()` BIG only

**Alignment score continu** :
- `align_TX_OY = sign(T) * sign(O) * min(|T|, |O|)`

## Resultats — Spearman vs forward 5b (sorte par rho_mean desc)

| Variant | n_days | rho_mean | rho_median | rho_p25 | rho_p75 | % positif | % significatif |
|---|---|---|---|---|---|---|---|
| `align_T3_O2` | 11 | 0.0463 | 0.0286 | -0.057 | 0.113 | 63.6% | 36.4% |
| `align_T1_O2` | 11 | 0.0384 | 0.015 | -0.0508 | 0.1101 | 54.5% | 27.3% |
| `align_T3_O1` | 11 | 0.028 | 0.0107 | -0.0668 | 0.1276 | 54.5% | 45.5% |
| `align_T1_O1` | 11 | 0.0261 | 0.0095 | -0.0442 | 0.0986 | 54.5% | 36.4% |
| `align_T2_O1` | 11 | 0.0096 | -0.0161 | -0.0636 | 0.0803 | 45.5% | 27.3% |
| `align_T2_O2` | 11 | 0.008 | -0.0197 | -0.0492 | 0.044 | 45.5% | 27.3% |

## Recommandation feature `trend_orderflow_alignment_20b`

**Variante GAGNANTE** : `align_T3_O2` (rho_mean = 0.0463)

- Stabilite : 36.4% des jours ont |rho| > 0.1
- Robustesse : 63.6% des jours ont signe correct

Formule recommandee :
```python
trend = (price_slope_20 + vwap_slope_10) / 2
orderflow = EMA(delta_bar, span=20)
alignment = sign(trend) * sign(orderflow) * min(|trend|, |orderflow|)
```
