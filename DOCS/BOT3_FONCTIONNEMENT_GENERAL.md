# Bot 3 — Fonctionnement general post-Phase 1.7b+1.7d

**Date** : 2026-05-17
**Statut** : revue complete apres implementation Phase 1.7b (commit f7caf40)
+ Phase 1.7d (en cours, code ecrit + tests 33/33 PASS).

## Vue d'ensemble : ce que Bot 3 N'EST PAS

**Bot 3 n'est PAS** un bot retail "touche le support = achat automatique".
A chaque touch de niveau, Bot 3 passe par **8 etapes obligatoires** d'analyse
contextuelle, applique 5 BLOCK + 12 BOOST empiriquement valides DSR Lopez=1.0,
et trace TOUT en logs JSONL pour audit.

## Pipeline complet d'un signal Bot 3

### Etape 0 — Construction du contexte (12 dimensions + 1 nouvelle Phase 1.7d)

Pour chaque barre 1m, `bot3_context_analyzer.analyze_context(bar)` extrait :

| DIM | Source v4 enriched (454 cols) | Sens trading |
|---|---|---|
| 1 Open Type + Day Type | `open_type`, `day_type` Dalton (OD/OTD/ORR + Trend/Normal/Neutral) | Caractere du jour |
| 2 POC migration | `poc_migration_dir`, `ctx_poc_migration_10`, `ctx_va_developing_10` | Direction institutionnelle |
| 3 Session + segment | `is_in_asia/london/us_cash/us_after` -> "ASIA"/"LONDON"/"US_CASH"/"US_AFTER" | Liquidite specifique |
| 4 Orderflow | `delta_bar`, `delta_pct`, `finish_strength`, `rvol`, `cvd_session/day`, `vol_zscore_20` | Qui paye maintenant |
| 5 Structure Dalton | `failed_auction`, `rotation_*`, `ib_extension_*`, `position_in_range` | Reading profile |
| 6 News proximity | `within_news_*_5m`, `mins_since_news` | Anti volatilite news |
| 7 Big traders | `n_big_bid/ask_t1-t4`, `*_cluster_*` | Whales presents ? |
| 8 Trapped traders | `n_trapped_buy/sell_cluster` | Squeeze potentiel |
| 9 Liquidity sweeps | `liq_sweep_high/low` + equal levels | Wyckoff spring detection |
| 10 Cross-instrument | `smt_divergence`, `cross_delta_agree` (ES↔NQ) | Confluence inter-marche |
| 11 ATR regime | `atr_14m_pct`, `atr_regime_zscore_60d` | Vol expansion vs contraction |
| 12 Roll day | `is_roll_day` | VETO si jour de roulement |
| **13** [J+7] | **`regime_bias_consensus`** (regime.favor + bias.direction) | **RESPECTER LA TENDANCE** (Phase 1.7a) |

### Etape 1 — Scan niveaux actifs (25 niveaux Bot 3)

`bot3_level_definitions.py` definit 25 niveaux groupes par TIER + bucket :

**TIER 1 (haute conviction, 10)** : SINGLE_PRINT, IB_LOW, MQ_PUT_0DTE, OPEN_830,
OPEN_930, GEX_DN, SIDAK_SWING_LOW/HIGH, SIDAK_COLOR_UP/DN_zone

**TIER 2 (CUR + VWAP MTF, 7)** : CUR_VPOC, GEX_DN, VWAP_W_SD1D, MQ_HVL, PVAL,
CASH_HIGH_CVD_FLAT, TRAPPED_SELL_OD

**TIER 3 (avec `required_context` strict, 8)** : MQ_CALL_POC_FLAT, PVAH, CUR_VAH,
MQ_CALL, IB_HIGH, SWING_HIGH, VWAP_D_SD1U/SD2U, PVWAP_SD1U

Pour chaque niveau, verifier `proximity_pct` (ex: `dist_pct <= 0.02%`).
Si non touche -> pass.

### Etape 2 — Decision (`bot3_decision_engine.evaluate_decision`)

**8 etapes obligatoires** dans l'ordre :

```
1. VETOS ABSOLUS (kill immediat)
   - VETO_ROLL_DAY si jour de roulement
   - VETO_NEWS_IMMINENT si news <5min
   - VETO_NEWS_JUST_HIT si news <3min passe
   - VETO_VOLUME_MORT si rvol < 0.30
   - VETO_MQ_STALE si MenthorQ ingestion >12h

1bis. [Phase 1.7b 17/05] BLOCK_COMBO Session × Level
   5 combos ES ASIA/LONDON catastrophiques (DSR_block=1.0) :
     ASIA SIDAK_SWING_HIGH / VWAP_W_SD1D / SIDAK_SWING_LOW
     LONDON CUR_VPOC / SINGLE_PRINT
   -> -1027 trades bloques / 6m + ~2893t pertes evitees

2. RESOLUTION SIDE
   - level["side"] == "LONG"/"SHORT"        -> side fixe
   - level["side"] == "REJECTION"           -> dist_signed positionnel
   - level["side"] == "NEUTRAL"             -> funnel 7 scenarios

2bis. NEUTRAL FUNNEL 7 SCENARIOS
   1. POC mig UP + VA expand + delta+finish UP -> LONG breakout
   2. POC mig DN + VA expand + delta+finish DN -> SHORT breakout
   3. POC FLAT + VA contract -> range day, fade
   4. Absorption bid/ask + finish contradictoire -> fade
   5. Liquidity sweep + retour -> Wyckoff spring/upthrust
   6. Big cluster + CVD divergence -> reversal
   7. Hammer/shooting star + body strong + vol_z>1 -> breakout confirme
   Si aucun match -> SKIP (funnel JSONL audit)

3. TIER 3 required_context (strict equality)
   Ex PVAL : cvd_trend==DOWN ET open_type in (3,4) ET position_in_range>=0.7
   Si un seul critere manque -> TIER3_MISS_xxx -> SKIP

4. FILTRE ANTI-TREND
   - side=SHORT + poc_dir=UP + speed > 0.05 -> SKIP_BULL_STRONG
   - side=SHORT + va_dev > 2.0              -> SKIP_VA_EXPANDING
   - side=LONG  + poc_dir=DN + speed <-0.05 -> SKIP_BEAR_STRONG

5. FILTRE ORDERFLOW (crush detection + acceptance/retest pattern)
   - LONG + delta tres negatif + finish negatif -> sellers ecrasent
     -> Si BOT3_TRADE_BREAKOUTS=True et tier<3 :
        -> PENDING_BREAKOUT_REGISTERED
        -> mp_engine attend 3-5 bars acceptance + retest 30 bars
        -> SIGNAL_GO si retest confirme, CRUSH_ABSORBED ou TIMEOUT sinon
     -> Sinon -> SKIP_SELLERS_CRUSHING
   - SHORT symetrique

6. CALCUL CONFIDENCE (baseline 50 + bonus tracking-only)
   Base : 50
   + whales : n_big_bid/ask t2,t3 selon side (+5 a +15)
   + liq_sweep aligne (+10)
   + failed_auction profile (+10)
   + cross_delta_agree ES/NQ (+10)
   + smt_divergence (+8)
   + trapped traders squeeze (+10)

   [Phase 1.7b 17/05] + SESSION_BOOST_CONFIDENCE si combo confirme :
     - NQ LONDON SIDAK_COLOR_UP_zone : +15 (PF 2.02 n=459)

   [Phase 1.7d 17/05] + SWING_COLOR_BOOSTED si confluence COLOR :
     11 combos (NQ surtout) :
     - NQ SIDAK_COLOR_UP_zone CONFLUENCE_STRONG : +15 (PF 1.93 n=1279)
     - NQ SIDAK_COLOR_DN_zone CONFLUENCE_STRONG : +15 (PF 1.87 n=865)
     - NQ SIDAK_COLOR_UP_zone CONFLUENCE_OK     : +20 (PF 3.40 n=429)
     - NQ SIDAK_COLOR_DN_zone CONFLUENCE_OK     : +20 (PF 3.48 n=272)
     - NQ SIDAK_SWING_HIGH    CONFLUENCE_STRONG : +15 (PF 1.62 n=268)
     - NQ SIDAK_SWING_LOW     CONFLUENCE_STRONG : +15 (PF 1.40 n=313)
     - NQ MQ_PUT_0DTE         CONFLUENCE_STRONG : +15 (PF 1.64 n=149)
     - NQ MQ_PUT_0DTE         CONFLUENCE_OK     : +10 (PF 1.45 n=96)
     - NQ SIDAK_SWING_LOW     CONFLUENCE_OK     : +10 (PF 1.42 n=87)
     - NQ SIDAK_SWING_HIGH    CONFLUENCE_OK     : +10 (PF 1.44 n=69)
     - ES SIDAK_SWING_LOW     CONFLUENCE_STRONG : +10 (PF 1.55 n=77)

   clamp [0, 100]

7. SL ADAPTATIF (ATR-based)
   atr_ratio = atr_14m_pct / ATR_BASELINE[symbol]    # {NQ:0.033, ES:0.027, MGC:0.035}
   clamp 0.7-1.5
   sl_ticks = GUARD_RAILS_BOT3[symbol]["sl_ticks_base"] * atr_multiplier

8. RETURN (True, "GO", params)
   params = {
     side, action, confidence, sl_ticks, atr_multiplier, atr_current,
     swing_color_consensus,           # toujours expose (tracking)
     boost_applied? swing_color_boost_applied?   # si applicable
   }
```

### Etape 3 — Execution avec garde-fous

- 1 position max par symbole + max trades/jour cap
- Cooldown post-close 30s (anti re-entry contre-sens)
- DTC bracket parent + TP + SL avec **OCO manuel** (cf `lessons.md` DTC)
- Snapshot bar-by-bar JSONL trade (audit complet 30 bars)
- Timeout 30 min -> **sequence anti-orphelin V2** (9 etapes obligatoires)

## Differences Bot 3 vs Bot 1 vs Bot 2

| Aspect | Bot 1 (paper rules) | Bot 2 V6 (live VPS) | Bot 3 (Sim1 paper) |
|---|---|---|---|
| Source signal | Dashboard rules + manuel | V6 brain + Databento V4 | 25 niveaux statiques + 12 dim contexte |
| STEP 0 regime gate | OUI strict (regime + bias + direction match) | OUI (regime.favor) | NON (sera Phase 1.7a J+7) |
| Niveaux statiques | Non | Non | OUI (25 TIER 1/2/3 + SIDAK) |
| Funnel NEUTRAL | Non | Non | OUI (7 scenarios) |
| Acceptance + retest | Non | Non | OUI (3-5 bars + 30 bars retest) |
| BLOCK historique | Non | Non | OUI (5 ES Phase 1.7b) |
| BOOST scoring | Non | Non | OUI (1 Phase 1.7b + 11 Phase 1.7d) |
| Logs tracability | Standard | Standard | Standard + funnel detaille + snapshots |

**Decouverte 22/04** : Bot 1 a fait +$665 en 35 min sur ES (trade live Topstep)
malgre son design "rules basiques" — preuve que la lecture humaine `cheminement
+ context` est valide. Bot 3 v2 industrialise cette philosophie.

## Stack BOOST/BLOCK applique par phase

| Phase | Date | Source | Effet mesure 6m enriched |
|---|---|---|---|
| 1.7b BLOCK 5 ES | commit f7caf40 17/05 | DSR Lopez Bonferroni n=1064 | -1027 trades + ~2893t evites |
| 1.7b BOOST 1 NQ | commit f7caf40 17/05 | DSR Bonferroni n=1064 | +15 conf sur 522 trades |
| **1.7d BOOST 11 confluence** | **en cours 17/05** | **DSR Lopez n=96** | **+10 a +20 conf sur ~6000 trades** |
| 1.7a regime_bias_consensus | J+7 | bonus +5 only (anti Pattern 11) | TODO |
| 1.7c BOOST ES US_CASH | J+14 si stable | re-eval CI [1.21, 2.71] | HOLD |
| 2.x BLOCK divergence | J+30 si n>=100 | DIVERGENCE COLOR PnL -15.7t/trade | TODO |

## Anti Pattern 11 V1 strict

Le V1 (`MIA_IA_system`) avait 11 layers cascades qui rejetaient 65% des signaux
valides. Bot 3 v2 evite ca par construction :

1. **1 BLOCK** Phase 1.7b (Session × Level catastrophiques) - validation DSR=1.0
2. **0 penalite** confidence (uniquement bonus)
3. **1 feature derivee** Phase 1.7d (`swing_color_consensus`)
4. **Stack borne** : clamp confidence [0, 100] (pas de cascade illimitee)
5. **Tracking-only** : aucun nouveau gate hardcode sans backtest
6. **DSR Lopez Bonferroni** sur tous les ajouts (n_trials adapte)
7. **Pas de combo** features composites (memoire `feedback_lightgbm_no_composite_indicators.md`)

## Traceability complete (regle souveraine 01/05)

Tous les codes log emit en production :
- `BOT3_LEVEL_CONTACT` (INFO) — touch detecte
- `BOT3_VETO_ROLL_DAY` / `BOT3_VETO_NEWS` / `BOT3_VETO_VOL_DEAD` (MAJEUR)
- `BOT3_VETO_MQ_STALE` (MAJEUR) — MenthorQ ingestion failed
- `BOT3_BLOCK_COMBO` (MAJEUR) — Phase 1.7b
- `BOT3_TIER3_MISS` (INFO) — required_context fail
- `BOT3_BOOST_APPLIED` (INFO) — Phase 1.7b session boost
- `BOT3_SWING_COLOR_BOOST` (INFO) — Phase 1.7d confluence boost
- `BOT3_BREAKOUT_RETEST_*` — state machine acceptance/crush/retest
- `BOT3_TRADE_OPEN` / `BOT3_TRADE_CLOSE` — execution
- `BOT3_TIMEOUT_*` (9 codes) — sequence anti-orphelin

## Limites connues + roadmap

### Limites actuelles
1. **Pas de STEP 0 regime gate** comme Bot 1 -> trades contre-tendance possibles
   (Phase 1.7a J+7 = `regime_bias_consensus +5` bonus alignement)
2. **6 mois v4 enriched seulement** -> audit J+30 sur 8m replay obligatoire
3. **ES SHORT pas d'edge** confirme empiriquement (0 BOOST ES SHORT)
4. **DIVERGENCE COLOR** identifiee (-15.7t/trade) mais n<100 par combo
   -> BLOCK Phase 2 apres validation 8m

### Roadmap immediate
- J0 deploy paper Sim1 (Phase 1.7b + 1.7d combines)
- J+1 verif logs : `grep BOT3_BLOCK_COMBO|BOT3_BOOST_APPLIED|BOT3_SWING_COLOR_BOOST LOGS/`
- J+7 Phase 1.7a regime_bias_consensus +5 si aligne
- J+14 Phase 1.7c BOOST ES US_CASH si 1.7b+1.7d+1.7a stables
- J+30 audit 8m enriched + Phase 2 BLOCK divergence si n>=100

## Cross-references

- `DOCS/BIAS_DIRECTION_DETECTION_CLARIFICATION.md` (Section A-E methodologie)
- `DOCS/BOT3_V2_CHANGES.md` (8 axes consolidation)
- `DOCS/BOT3_V2_PHASE1_0_AUDIT_REPORT.md` (audit nuit 17/05)
- `DOCS/BOT_CHANGELOG.md` (entry 17/05 04:30 Phase 1.7b)
- `tools/bot3_v2_phase1_0_audit.py` (audit DSR Lopez Bonferroni 1064)
- `tools/audit_color_vs_longbar_comparison.py` (comparatif 3 approches Phase 1.7d)
- `.claude/rules/orphan-prevention.md` (sequence anti-orphelin V2)
- `.claude/rules/critical-tasks-review.md` (review agent obligatoire)
- `.claude/memory/feedback_lightgbm_no_composite_indicators.md` (anti Pattern 11)
- `.claude/memory/feedback_cross_instrument_bonus_not_gate.md` (bonus only doctrine)
