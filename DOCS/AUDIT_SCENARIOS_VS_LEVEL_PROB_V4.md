# AUDIT SCENARIOS DirectionResolver vs LEVEL_PROB_V4

**Genere** : `tools/audit_scenarios_vs_level_prob_v4.py`

**Sources empiriques** :
- `DOCS/LEVEL_PROB_V4_NQ.md` : 55 levels parses (356K bars NQ, 318j)
- `DOCS/LEVEL_PROB_V4_ES.md` : 55 levels parses (357K bars ES, 318j)

**Seuils verdict** : PF_VALIDATED >= 1.3, PF_MARGINAL >= 1.1, PF_CONTEXT_BOOST >= 2.0, N_MIN >= 30.

## Summary

| Verdict | Count |
|---|---|
| VALIDATED_STRONG | 5 |
| VALIDATED | 2 |
| VALIDATED_WEAK | 0 |
| MARGINAL_CTX | 0 |
| NO_EMPIRICAL_CTX | 1 |
| NO_EMPIRICAL_DIM | 2 |
| NO_EDGE | 0 |
| TOTAL | 10 |

## Detail par scenario

### S01_OD_UP_support_bounce — VALIDATED_STRONG

- **NarrativeState** : `OPEN_DRIVE_UP`
- **level_nature** : `support`
- **side** : `LONG`
- **Canon** : Dalton MOM Ch.7 — Open Drive momentum continuation
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `open_type=T0`
- **Reason** : 1 level(s) avec context match. top_ctx_pf=13.07 sur NQ:TRAPPED_SELL (open_type=T0)

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | TRAPPED_SELL | 494 | 46.4% | 0.70 | `open_type=T0` | 13.07 | CTX |
| NQ | MQ_PUT_0DTE | 497 | 57.5% | 1.80 | `day_type=T1` | 5.05 | BASE |
| NQ | GEX_DN | 2346 | 55.1% | 1.34 | `session=US_AFTER` | 7.97 | BASE |
| NQ | PVAL | 15395 | 53.4% | 1.11 | `-` | - | BASE |
| NQ | DELTA_DIV_BUY | 76227 | 51.8% | 1.10 | `-` | - | BASE |
| ES | MQ_PUT | 182 | 62.1% | 4.89 | `session=LONDON` | 40.85 | BASE |
| ES | MQ_PUT_0DTE | 343 | 58.0% | 2.00 | `-` | - | BASE |
| ES | GEX_DN | 5708 | 54.8% | 1.16 | `session=OTHER` | 8.67 | BASE |
| ES | DELTA_DIV_BUY | 96017 | 52.6% | 1.10 | `cvd_trend=FLAT` | 3.78 | BASE |
| ES | MQ_1D_MIN | 854 | 51.8% | 1.14 | `ib_status=BROKEN_DN` | 11.74 | BASE |

### S02_OD_DOWN_resistance_rejection — VALIDATED

- **NarrativeState** : `OPEN_DRIVE_DOWN`
- **level_nature** : `resistance`
- **side** : `SHORT`
- **Canon** : Dalton MOM Ch.7 — Open Drive momentum continuation
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `open_type=T0`
- **Reason** : 1 level(s) avec context match. top_ctx_pf=2.45 sur NQ:TRAPPED_BUY (open_type=T0)

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | TRAPPED_BUY | 588 | 40.3% | 0.95 | `open_type=T0` | 2.45 | CTX |
| NQ | MQ_CALL | 403 | 46.4% | 1.12 | `range_pos=TOP` | 5.92 | BASE |
| ES | MQ_CALL_0DTE | 1475 | 55.7% | 1.35 | `session=US_AFTER` | 3.82 | BASE |
| ES | IB_HIGH | 50969 | 51.8% | 1.21 | `-` | - | BASE |
| ES | MQ_CALL | 742 | 51.1% | 1.30 | `poc_mig=FLAT` | 5.42 | BASE |

### S03_TREND_UP_support_pullback — VALIDATED_STRONG

- **NarrativeState** : `TREND_UP_CONTINUATION`
- **level_nature** : `support`
- **side** : `LONG`
- **Canon** : Dalton MOM Ch.10 Trend Day pullback entry
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `day_type=T1`
- **Reason** : 1 level(s) avec context match. top_ctx_pf=5.05 sur NQ:MQ_PUT_0DTE (day_type=T1)

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | MQ_PUT_0DTE | 497 | 57.5% | 1.80 | `day_type=T1` | 5.05 | BASE+CTX |
| NQ | GEX_DN | 2346 | 55.1% | 1.34 | `session=US_AFTER` | 7.97 | BASE |
| NQ | PVAL | 15395 | 53.4% | 1.11 | `-` | - | BASE |
| NQ | DELTA_DIV_BUY | 76227 | 51.8% | 1.10 | `-` | - | BASE |
| ES | MQ_PUT | 182 | 62.1% | 4.89 | `session=LONDON` | 40.85 | BASE |
| ES | MQ_PUT_0DTE | 343 | 58.0% | 2.00 | `-` | - | BASE |
| ES | GEX_DN | 5708 | 54.8% | 1.16 | `session=OTHER` | 8.67 | BASE |
| ES | DELTA_DIV_BUY | 96017 | 52.6% | 1.10 | `cvd_trend=FLAT` | 3.78 | BASE |
| ES | MQ_1D_MIN | 854 | 51.8% | 1.14 | `ib_status=BROKEN_DN` | 11.74 | BASE |

### S04_TREND_DOWN_resistance_pullback — NO_EMPIRICAL_CTX

- **NarrativeState** : `TREND_DOWN_CONTINUATION`
- **level_nature** : `resistance`
- **side** : `SHORT`
- **Canon** : Dalton MOM Ch.10 Trend Day pullback entry (biais histo bullish limite mesure)
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `day_type=T1`, `day_type=T2`, `day_type=T6`
- **Reason** : Aucun level avec best_rej_ctx match expected=['day_type=T1', 'day_type=T2', 'day_type=T6']. 4 level(s) ont une baseline PF>=1.10 (borne sup, pas une preuve scenario).

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | MQ_CALL | 403 | 46.4% | 1.12 | `range_pos=TOP` | 5.92 | BASE |
| ES | MQ_CALL_0DTE | 1475 | 55.7% | 1.35 | `session=US_AFTER` | 3.82 | BASE |
| ES | IB_HIGH | 50969 | 51.8% | 1.21 | `-` | - | BASE |
| ES | MQ_CALL | 742 | 51.1% | 1.30 | `poc_mig=FLAT` | 5.42 | BASE |

### S05_SPRING_recovery_long — NO_EMPIRICAL_DIM

- **NarrativeState** : `WYCKOFF_SPRING_LONG`
- **level_nature** : `support`
- **side** : `LONG`
- **Canon** : Wyckoff Phase C Spring (Pruden Three Skills Ch.7)
- **Reason** : Scenario rare event (Wyckoff Spring/Upthrust, exhaustion sans ctx). LEVEL_PROB_V4 ne fournit pas de dimension contextuelle dediee — validation requiert backtest event-detection sur swing pivots.

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | MQ_PUT_0DTE | 497 | 57.5% | 1.80 | `day_type=T1` | 5.05 | BASE |
| NQ | GEX_DN | 2346 | 55.1% | 1.34 | `session=US_AFTER` | 7.97 | BASE |
| NQ | PVAL | 15395 | 53.4% | 1.11 | `-` | - | BASE |
| NQ | DELTA_DIV_BUY | 76227 | 51.8% | 1.10 | `-` | - | BASE |
| ES | MQ_PUT | 182 | 62.1% | 4.89 | `session=LONDON` | 40.85 | BASE |
| ES | MQ_PUT_0DTE | 343 | 58.0% | 2.00 | `-` | - | BASE |
| ES | GEX_DN | 5708 | 54.8% | 1.16 | `session=OTHER` | 8.67 | BASE |
| ES | DELTA_DIV_BUY | 96017 | 52.6% | 1.10 | `cvd_trend=FLAT` | 3.78 | BASE |
| ES | MQ_1D_MIN | 854 | 51.8% | 1.14 | `ib_status=BROKEN_DN` | 11.74 | BASE |

### S06_UPTHRUST_rejection_short — NO_EMPIRICAL_DIM

- **NarrativeState** : `WYCKOFF_UPTHRUST_SHORT`
- **level_nature** : `resistance`
- **side** : `SHORT`
- **Canon** : Wyckoff Phase C Upthrust (Pruden Three Skills Ch.7)
- **Reason** : Scenario rare event (Wyckoff Spring/Upthrust, exhaustion sans ctx). LEVEL_PROB_V4 ne fournit pas de dimension contextuelle dediee — validation requiert backtest event-detection sur swing pivots.

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | MQ_CALL | 403 | 46.4% | 1.12 | `range_pos=TOP` | 5.92 | BASE |
| ES | MQ_CALL_0DTE | 1475 | 55.7% | 1.35 | `session=US_AFTER` | 3.82 | BASE |
| ES | IB_HIGH | 50969 | 51.8% | 1.21 | `-` | - | BASE |
| ES | MQ_CALL | 742 | 51.1% | 1.30 | `poc_mig=FLAT` | 5.42 | BASE |

### S07_RANGE_support_long — VALIDATED

- **NarrativeState** : `RANGE_RESPECTED`
- **level_nature** : `support`
- **side** : `LONG`
- **Canon** : Dalton MOM Ch.9 Range Day fade
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `day_type=T3`, `day_type=T4`, `day_type=T5`, `open_type=T2`, `open_type=T3`, `va_dev=STABLE`
- **Reason** : 2 level(s) avec context match. top_ctx_pf=3.10 sur NQ:GEX_DN (va_dev=STABLE)

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | GEX_DN | 2346 | 55.1% | 1.34 | `session=US_AFTER` | 7.97 | BASE+CTX |
| ES | CASH_LOW | 12400 | 49.0% | 0.96 | `open_type=T2` | 3.07 | CTX |
| NQ | MQ_PUT_0DTE | 497 | 57.5% | 1.80 | `day_type=T1` | 5.05 | BASE |
| NQ | PVAL | 15395 | 53.4% | 1.11 | `-` | - | BASE |
| NQ | DELTA_DIV_BUY | 76227 | 51.8% | 1.10 | `-` | - | BASE |
| ES | MQ_PUT | 182 | 62.1% | 4.89 | `session=LONDON` | 40.85 | BASE |
| ES | MQ_PUT_0DTE | 343 | 58.0% | 2.00 | `-` | - | BASE |
| ES | GEX_DN | 5708 | 54.8% | 1.16 | `session=OTHER` | 8.67 | BASE |
| ES | DELTA_DIV_BUY | 96017 | 52.6% | 1.10 | `cvd_trend=FLAT` | 3.78 | BASE |
| ES | MQ_1D_MIN | 854 | 51.8% | 1.14 | `ib_status=BROKEN_DN` | 11.74 | BASE |

### S08_RANGE_resistance_short — VALIDATED_STRONG

- **NarrativeState** : `RANGE_RESPECTED`
- **level_nature** : `resistance`
- **side** : `SHORT`
- **Canon** : Dalton MOM Ch.9 Range Day fade
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `day_type=T3`, `day_type=T4`, `day_type=T5`, `open_type=T2`, `open_type=T3`, `va_dev=STABLE`
- **Reason** : 3 level(s) avec context match. top_ctx_pf=7.96 sur NQ:CASH_HIGH (open_type=T2)

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | CASH_HIGH | 12035 | 47.3% | 0.90 | `cvd_trend=FLAT` | 11.26 | CTX |
| ES | MQ_CALL_0DTE | 1475 | 55.7% | 1.35 | `session=US_AFTER` | 3.82 | BASE+CTX |
| ES | CASH_HIGH | 26093 | 46.9% | 0.92 | `open_type=T2` | 3.83 | CTX |
| NQ | MQ_CALL | 403 | 46.4% | 1.12 | `range_pos=TOP` | 5.92 | BASE |
| ES | IB_HIGH | 50969 | 51.8% | 1.21 | `-` | - | BASE |
| ES | MQ_CALL | 742 | 51.1% | 1.30 | `poc_mig=FLAT` | 5.42 | BASE |

### S09_EXHAUSTION_TOP_short — VALIDATED_STRONG

- **NarrativeState** : `EXHAUSTION_TOP`
- **level_nature** : `resistance`
- **side** : `SHORT`
- **Canon** : Wyckoff buying climax (Pruden Ch.7)
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `cvd_trend=FLAT`, `range_pos=TOP`
- **Reason** : 5 level(s) avec context match. top_ctx_pf=11.26 sur NQ:CASH_HIGH (cvd_trend=FLAT)

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| NQ | CASH_HIGH | 12035 | 47.3% | 0.90 | `cvd_trend=FLAT` | 11.26 | CTX |
| NQ | MQ_CALL | 403 | 46.4% | 1.12 | `range_pos=TOP` | 5.92 | BASE+CTX |
| ES | OVN_HIGH | 36121 | 39.9% | 0.56 | `cvd_trend=FLAT` | 3.37 | CTX |
| ES | SWING_HIGH | 148898 | 49.9% | 0.83 | `cvd_trend=FLAT` | 1.87 | CTX |
| NQ | GEX_UP | 2449 | 46.7% | 0.85 | `cvd_trend=FLAT` | 1.54 | CTX |
| ES | MQ_CALL_0DTE | 1475 | 55.7% | 1.35 | `session=US_AFTER` | 3.82 | BASE |
| ES | IB_HIGH | 50969 | 51.8% | 1.21 | `-` | - | BASE |
| ES | MQ_CALL | 742 | 51.1% | 1.30 | `poc_mig=FLAT` | 5.42 | BASE |

### S10_EXHAUSTION_BOTTOM_long — VALIDATED_STRONG

- **NarrativeState** : `EXHAUSTION_BOTTOM`
- **level_nature** : `support`
- **side** : `LONG`
- **Canon** : Wyckoff selling climax (Pruden Ch.7)
- **Expected ctx (LEVEL_PROB best_rej_ctx)** : `cvd_trend=FLAT`, `range_pos=BOT`
- **Reason** : 2 level(s) avec context match. top_ctx_pf=4.93 sur ES:TRAPPED_SELL (range_pos=BOT)

| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |
|---|---|---|---|---|---|---|---|
| ES | TRAPPED_SELL | 38574 | 53.5% | 1.00 | `range_pos=BOT` | 4.93 | CTX |
| ES | DELTA_DIV_BUY | 96017 | 52.6% | 1.10 | `cvd_trend=FLAT` | 3.78 | BASE+CTX |
| NQ | MQ_PUT_0DTE | 497 | 57.5% | 1.80 | `day_type=T1` | 5.05 | BASE |
| NQ | GEX_DN | 2346 | 55.1% | 1.34 | `session=US_AFTER` | 7.97 | BASE |
| NQ | PVAL | 15395 | 53.4% | 1.11 | `-` | - | BASE |
| NQ | DELTA_DIV_BUY | 76227 | 51.8% | 1.10 | `-` | - | BASE |
| ES | MQ_PUT | 182 | 62.1% | 4.89 | `session=LONDON` | 40.85 | BASE |
| ES | MQ_PUT_0DTE | 343 | 58.0% | 2.00 | `-` | - | BASE |
| ES | GEX_DN | 5708 | 54.8% | 1.16 | `session=OTHER` | 8.67 | BASE |
| ES | MQ_1D_MIN | 854 | 51.8% | 1.14 | `ib_status=BROKEN_DN` | 11.74 | BASE |

## Interpretation (mode STRICT)

- **VALIDATED_STRONG** : >=1 level avec context match ET context_pf >= 4.0 (edge selectif fort).
- **VALIDATED** : >=1 level avec context match ET context_pf >= 2.0 (edge selectif robuste).
- **VALIDATED_WEAK** : >=1 level avec context match ET context_pf >= 1.3 (edge selectif marginal).
- **MARGINAL_CTX** : context match mais context_pf in [1.10, 1.30) (douteux).
- **NO_EMPIRICAL_CTX** : aucun level avec best_rej_ctx matchant le scenario. La 
  baseline existe mais ne valide PAS le scenario (recyclage de baseline = Pattern 11 V1).
- **NO_EMPIRICAL_DIM** : scenario rare event (Wyckoff) — LEVEL_PROB_V4 ne mesure 
  pas la dimension event-based. Validation requiert backtest event-detection dedie.
- **NO_EDGE** : aucun level avec edge baseline ni contextuel.

**Limite methodologique** : LEVEL_PROB_V4 mesure rejection 30min baseline + 
best_rej_ctx, pas la sequence narrative complete (state + level_nature + 
confirmation pattern). Le mode STRICT n'accepte un scenario VALIDATED que si 
LEVEL_PROB_V4 fournit un best_rej_ctx qui matche la condition narrative. Sinon : 
incertain (NO_EMPIRICAL_CTX ou NO_EMPIRICAL_DIM) et walk-forward DSR Lopez 
Phase 5 obligatoire avant tout switch live.
