# Pullback Continuation Battery — Setup Jackson

**Date** : 2026-04-27 21:21

**Pattern observe** : prix monte → pullback color_up + long_dn_up bar → repart

**TB** : K_SL=1.5 K_TP=2.0 H=60

## Top par PF

| # | Code | Variante | Sym | Trades | WR | PF | EV | Sharpe | MC_p | BH | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | P03 | BUY pullback + MQ HVL confluence | NQ | 66 | 42.4% | 1.49 | +35.4t | 3.92 | 0.721 | no | NO-GO (MC>0.10) |
| 2 | P04 | BUY pullback + n_color_up_zones >= 5 | ES | 112 | 46.4% | 1.34 | +4.9t | 3.23 | 0.527 | no | NO-GO (MC>0.10) |
| 3 | P02 | BUY pullback + above VWAP_d (trend strict) | ES | 66 | 48.5% | 1.33 | +4.9t | 2.53 | 0.832 | no | NO-GO (MC>0.10) |
| 4 | P01 | BUY pullback simple (delta+color_up+long_dn_up) | ES | 180 | 46.1% | 1.33 | +5.2t | 3.03 | 0.483 | no | NO-GO (MC>0.10) |
| 5 | P05 | SELL pullback + below VWAP_d (full symm) | ES | 118 | 45.8% | 1.31 | +4.8t | 2.87 | 0.790 | no | NO-GO (MC>0.10) |
| 6 | P02 | BUY pullback + above VWAP_d (trend strict) | NQ | 287 | 39.4% | 1.24 | +15.9t | 2.40 | 0.964 | no | NO-GO (PF<1.3) |
| 7 | P05 | SELL pullback + below VWAP_d (full symm) | NQ | 263 | 40.3% | 1.22 | +16.2t | 1.92 | 0.455 | no | NO-GO (PF<1.3) |
| 8 | P06 | SELL pullback simple | ES | 266 | 41.7% | 1.15 | +2.3t | 1.53 | 0.879 | no | NO-GO (PF<1.3) |
| 9 | P06 | SELL pullback simple | NQ | 612 | 37.9% | 1.11 | +7.8t | 1.18 | 0.562 | no | NO-GO (PF<1.3) |
| 10 | P07 | BUY pullback + trapped_sellers_at_support OR | ES | 328 | 40.9% | 1.09 | +1.3t | 0.98 | 0.578 | no | NO-GO (PF<1.3) |
| 11 | P01 | BUY pullback simple (delta+color_up+long_dn_up) | NQ | 653 | 37.2% | 1.06 | +4.6t | 0.74 | 0.349 | no | NO-GO (PF<1.3) |
| 12 | P04 | BUY pullback + n_color_up_zones >= 5 | NQ | 602 | 36.9% | 1.06 | +4.0t | 0.66 | 0.076 | no | NO-GO (PF<1.3) |
| 13 | P08 | BUY pullback + edge_buy_fire OR | NQ | 865 | 36.4% | 1.02 | +1.7t | 0.25 | 0.043 | no | NO-GO (PF<1.3) |
| 14 | P07 | BUY pullback + trapped_sellers_at_support OR | NQ | 739 | 35.2% | 1.00 | +0.0t | 0.00 | 0.104 | no | NO-GO (PF<1.3) |
| 15 | P08 | BUY pullback + edge_buy_fire OR | ES | 750 | 35.3% | 0.88 | -1.9t | -1.37 | 0.031 | no | NO-GO (PF<1.3) |

## Variantes non-evaluables (signals < 10)

- P03 BUY pullback + MQ HVL confluence (ES) : 12 signaux, 12 trades
