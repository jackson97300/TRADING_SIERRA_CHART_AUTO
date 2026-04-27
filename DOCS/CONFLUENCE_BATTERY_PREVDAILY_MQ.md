# Confluence Battery Previous Daily + MenthorQ

**Date** : 2026-04-27 21:16

**Source** : ES/NQ_dataset_v5c.parquet (24m, 351K bars)
**Triple Barrier** : K_SL=1.5 K_TP=2.0 H=60
**Prox threshold** : 0.1% (10 ticks ES @4500)
**Costs** : ES 2.3t, NQ 5.2t

## Top par PF (n_trades >= 30, PF descendant)

| Rang | Code | Confluence | Sym | Trades | WR | PF | EV | Sharpe | MC_p | BH | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | C07 | SELL mq_call_0dte gamma resist | NQ | 155 | 38.7% | 1.42 | +21.6t | 2.70 | 0.202 | no | NO-GO (MC p>0.10) |
| 2 | C08 | BUY mq_hvl + delta up | NQ | 126 | 42.9% | 1.38 | +23.7t | 3.42 | 0.446 | no | NO-GO (MC p>0.10) |
| 3 | C14 | BUY pvwap_sd1d (oversold) | NQ | 803 | 35.2% | 1.00 | +0.1t | 0.02 | 0.007 | no | NO-GO (PF<1.3) |
| 4 | C03 | BUY prev_val proximity | NQ | 755 | 36.4% | 0.95 | -2.9t | -0.50 | 0.440 | no | NO-GO (PF<1.3) |
| 5 | C18 | SELL triple resist (vah × call × gex) | ES | 164 | 37.8% | 0.94 | -0.4t | -0.44 | 0.834 | no | NO-GO (PF<1.3) |
| 6 | C01 | BUY pdl proximity | NQ | 502 | 32.9% | 0.89 | -7.0t | -1.00 | 0.614 | no | NO-GO (PF<1.3) |
| 7 | C06 | BUY mq_put_0dte gamma support | NQ | 48 | 27.1% | 0.88 | -9.0t | -1.32 | 0.875 | no | NO-GO (PF<1.3) |
| 8 | C16 | BUY/SELL naked_poc + delta | NQ | 687 | 34.9% | 0.88 | -4.6t | -1.29 | 0.121 | no | NO-GO (PF<1.3) |
| 9 | C12 | SELL pdh × mq_call | ES | 148 | 32.4% | 0.86 | -1.5t | -1.18 | 0.655 | no | NO-GO (PF<1.3) |
| 10 | C15 | SELL pvwap_sd1u (overbought) | NQ | 942 | 34.5% | 0.84 | -5.5t | -1.72 | 0.072 | no | NO-GO (PF<1.3) |
| 11 | C02 | SELL pdh proximity | NQ | 731 | 31.3% | 0.83 | -6.9t | -1.64 | 0.548 | no | NO-GO (PF<1.3) |
| 12 | C10 | SELL prev_vah × mq_call_0dte | ES | 186 | 37.6% | 0.82 | -1.6t | -2.22 | 0.914 | no | NO-GO (PF<1.3) |
| 13 | C03 | BUY prev_val proximity | ES | 783 | 35.0% | 0.82 | -1.8t | -1.72 | 0.058 | no | NO-GO (PF<1.3) |
| 14 | C05 | BUY pvwap proximity | NQ | 858 | 37.4% | 0.80 | -8.4t | -2.07 | 0.247 | no | NO-GO (PF<1.3) |
| 15 | C08 | BUY mq_hvl + delta up | ES | 106 | 38.7% | 0.80 | -3.7t | -2.13 | 0.070 | no | NO-GO (PF<1.3) |
| 16 | C16 | BUY/SELL naked_poc + delta | ES | 725 | 34.1% | 0.79 | -1.8t | -2.45 | 0.715 | no | NO-GO (PF<1.3) |
| 17 | C04 | SELL prev_vah proximity | NQ | 913 | 32.9% | 0.77 | -8.3t | -2.31 | 0.886 | no | NO-GO (PF<1.3) |
| 18 | C01 | BUY pdl proximity | ES | 494 | 33.2% | 0.76 | -3.2t | -2.42 | 0.727 | no | NO-GO (PF<1.3) |
| 19 | C02 | SELL pdh proximity | ES | 773 | 34.5% | 0.74 | -2.3t | -2.83 | 0.939 | no | NO-GO (PF<1.3) |
| 20 | C06 | BUY mq_put_0dte gamma support | ES | 49 | 30.6% | 0.73 | -4.7t | -4.02 | 0.333 | no | NO-GO (PF<1.3) |
| 21 | C04 | SELL prev_vah proximity | ES | 996 | 33.2% | 0.66 | -2.8t | -4.10 | 0.913 | no | NO-GO (PF<1.3) |
| 22 | C20 | SELL pdh × call_0dte × blind_up | NQ | 120 | 32.5% | 0.65 | -20.8t | -3.43 | 0.988 | no | NO-GO (PF<1.3) |
| 23 | C14 | BUY pvwap_sd1d (oversold) | ES | 812 | 33.4% | 0.64 | -3.7t | -3.88 | 0.660 | no | NO-GO (PF<1.3) |
| 24 | C10 | SELL prev_vah × mq_call_0dte | NQ | 121 | 26.4% | 0.63 | -17.6t | -4.46 | 0.838 | no | NO-GO (PF<1.3) |
| 25 | C07 | SELL mq_call_0dte gamma resist | ES | 193 | 32.1% | 0.61 | -5.7t | -5.58 | 0.718 | no | NO-GO (PF<1.3) |
| 26 | C15 | SELL pvwap_sd1u (overbought) | ES | 1012 | 32.7% | 0.61 | -3.4t | -4.50 | 0.771 | no | NO-GO (PF<1.3) |
| 27 | C05 | BUY pvwap proximity | ES | 883 | 32.0% | 0.60 | -3.5t | -4.30 | 0.142 | no | NO-GO (PF<1.3) |
| 28 | C20 | SELL pdh × call_0dte × blind_up | ES | 169 | 31.4% | 0.58 | -4.0t | -6.71 | 0.659 | no | NO-GO (PF<1.3) |
| 29 | C12 | SELL pdh × mq_call | NQ | 114 | 28.9% | 0.57 | -21.2t | -5.22 | 0.916 | no | NO-GO (PF<1.3) |
| 30 | C13 | BUY pvwap × mq_hvl | ES | 69 | 33.3% | 0.47 | -7.0t | -7.76 | 0.991 | no | NO-GO (PF<1.3) |
| 31 | C18 | SELL triple resist (vah × call × gex) | NQ | 92 | 19.6% | 0.29 | -32.7t | -9.14 | 0.552 | no | NO-GO (PF<1.3) |

## Confluences non-evaluables (signals < 10)

- C09 BUY prev_val × mq_put_0dte (ES) : 33 signaux
- C11 BUY pdl × mq_put (ES) : 13 signaux
- C17 BUY triple support (val × put × gex) (ES) : 0 signaux
- C19 BUY pdl × put_0dte × blind_dn (ES) : 124 signaux
- C09 BUY prev_val × mq_put_0dte (NQ) : 57 signaux
- C11 BUY pdl × mq_put (NQ) : 10 signaux
- C13 BUY pvwap × mq_hvl (NQ) : 41 signaux
- C17 BUY triple support (val × put × gex) (NQ) : 0 signaux
- C19 BUY pdl × put_0dte × blind_dn (NQ) : 34 signaux
