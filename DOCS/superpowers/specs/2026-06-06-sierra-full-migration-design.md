# Sierra Chart Full Migration — Design Doc

**Date** : 2026-06-06 (samedi)
**Auteur** : Jackson + Claude
**Statut** : DRAFT — review Plan agent obligatoire avant code
**Branche cible** : `feat/sierra-full-migration`

---

## 0. TL;DR

Migration totale pipeline donnees de **Databento + Python** vers **Sierra Chart DMP (C++) + Python recalc**.
Objectifs :
1. **Fixer bug delta_bar inverse** (confirme NautilusTrader decoder) qui pollue 3 bots depuis le debut
2. **Economiser $179/mois** (+ $411 invoice impayee si renouvellement evite)
3. **Eliminer dependance Databento** (subscription expire 2026-07-01)
4. **Simplifier architecture** (1 source au lieu de 2)
5. **Reproductibilite** : Sierra contient deja 87 features stables AS-IS, ~50 a creer Python

**Deadline implicite** : 2026-07-01 (renouvellement Databento). 25 jours.

**Coverage cible** : 100% des features actuelles Databento (130+) reproduites depuis Sierra + Python.

---

## 1. Motivation (impitoyable)

### 1.1 Bug delta_bar inverse — preuve canonique

NautilusTrader Rust decoder (https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/adapters/databento/src/decode.rs) :

```rust
pub const fn parse_aggressor_side(c: c_char) -> AggressorSide {
    match c as u8 as char {
        'A' => AggressorSide::Seller,   // Side.ASK = SELLER aggressor
        'B' => AggressorSide::Buyer,    // Side.BID = BUYER aggressor
        _ => AggressorSide::NoAggressor,
    }
}
```

**Notre code Python `CORE/enricher_chain.py:321-324`** :
```python
if _trade.side == "A":
    delta_bar_total += s   # FAUX : on suppose BUYER, en realite SELLER
elif _trade.side == "B":
    delta_bar_total -= s   # FAUX : on suppose SELLER, en realite BUYER
```

Inversion COMPLETE. Confirme empiriquement sur 5 jours baissiers consecutifs (NQ 20260519, 27, 0603, 0604, 0605) :
- Sierra `delta_bar` sum : negatif (vendeurs, COHERENT marche baissier)
- Databento `delta_bar` sum : positif (acheteurs, INVERSE)
- Ranges miroirs (Sierra [-799..641] vs Databento [-641..799])

### 1.2 Impact bots actuels (Bot 1, 2, 3)

| Bot | Lecture `delta_bar` | Decision live | Realite |
|---|---|---|---|
| Bot 1 V3 NQ | `delta_bar > 0` = bullish | LONG dans la chute | acheteurs faux |
| Bot 2 BN V5 | `delta_bar > 0` = LONG | LONG dans chute | gate inverse |
| Bot 3 V4 | `delta_bar < 0` = SHORT confirm | bloque SHORT | manque SHORT |

Confirme : "les bots ont achete tout au long de la baisse" (Jackson observation).

### 1.3 Economie

- Databento subscription : **$179/mois**
- Invoice impayee : **$411** (juin 2026, overage)
- Total economies 12 mois : ~$2,500

### 1.4 Sierra deja en place

- DMP C++ fonctionnel depuis 6 mois (schema 3.7.14, 268 features)
- VPS Windows tourne deja Sierra Chart + DMP
- Convention `delta_bar = AskVolume - BidVolume` (saine, conforme industrie)
- 87 features stables identifiees par audit 20260605

---

## 2. Architecture cible

### 2.1 Avant (actuel)

```
+----------------+     +----------------+
|  Sierra Chart  |     |   Databento    |
|     DMP C++    |     |   API live     |
+-------+--------+     +--------+-------+
        |                       |
        v                       v
   JSONL Sierra            JSONL trades + bars
   (DATA/NQ/*.jsonl)       (DATA/LIVE_CACHE/)
        |                       |
        +-----------+-----------+
                    |
                    v
        +--------------------+
        |  enricher_chain.py |   <-- BUG delta_bar inverse ici
        |  (Python pipeline) |
        +---------+----------+
                  |
                  v
        DATA/live_enriched/NQ/*.jsonl   (489 features)
                  |
                  v
        +---------+----------+
        |  Bot 1 / 2 / 3     |
        +--------------------+
```

### 2.2 Apres (cible)

```
+----------------+
|  Sierra Chart  |
|     DMP C++    |
+-------+--------+
        |
        v
   JSONL Sierra
   (DATA/NQ/*.jsonl)
        |
        v
+----------------------+
|  sierra_live_io.py   |   <-- NEW : lecteur stream tail-follow
+----------+-----------+
           |
           v
+------------------------+
|  enricher_sierra.py    |   <-- Refactor enricher_chain
|                        |       (source-agnostic deja)
|  + POC migration       |   <-- NEW module
|  + Swings enrichi      |   <-- NEW module
|  + Divergences enrichi |   <-- NEW module
|  + Prev levels         |   <-- NEW module
|  + Sessions fine       |   <-- NEW module
|  + CTX rolling         |   <-- NEW module
|  + Roll calendar       |   <-- NEW module
|  + News calendar       |   <-- NEW module
|  + Intermarket (deja)  |   <-- compat verification
|  + Regime engine (deja)|   <-- no change
+----------+-------------+
           |
           v
DATA/live_enriched_sierra/NQ/*.jsonl   (130+ features cible)
           |
           v
+---------+----------+
|  Bot 1 / 2 / 3     |
+--------------------+
```

### 2.3 Frontiere claire

`enricher_chain.compose_enriched_payload()` est deja une **fonction pure source-agnostic**. La migration consiste a :
1. Remplacer le PRODUCTEUR de bars (databento -> sierra_live_io)
2. Ajouter ~50 features Python pour combler les absences Sierra
3. Garder le RESTE du pipeline inchange

---

## 3. Inventaire features Sierra AS-IS (87 stables)

Source : `DOCS/AUDIT_SIERRA_VS_DATABENTO_20260605.md` (1003 lignes).

### 3.1 OHLCV + Base (8)
`price`, `atr`, `atr_14m`, `session`, `session_id`, `ts`, `bar_high`, `bar_low`

### 3.2 VWAP D/W/M + SD bands (19)
`dist_vwap_d`, `dist_vwap_d_atr`, `dist_vwap_d_sd1u/d/sd2u/d/sd3u/d`,
`dist_vwap_w`, `dist_vwap_w_atr`, `dist_vwap_m`, `dist_vwap_m_atr`,
`vwap_d_side`, `vwap_w_side`, `vwap_m_side`,
`vwap_slope_10`, `vwap_slope_30`, `vwap_slope_10_dir`

### 3.3 Volume Profile current/prev/composite (~26)
`dist_cur_vpoc`, `dist_cur_vah/val`, `dist_cur_vwap_vp`,
`va_position_pct`, `inside_cur_va`, `range_pos`, `range_size_ticks`,
`vah_touches_20b`, `val_touches_20b`, `bars_in_va`,
`dist_prev_vpoc/vah/val`, `inside_prev_va`, `open_in_prev_va`,
`dist_comp_20d_vpoc/vah/val/vwap`, `dist_comp_50d_vpoc`,
`inside_comp_20d_va`, `inside_comp_50d_va`, `comp_vpoc_align_20_50`

### 3.4 Niveaux veille + Cash + Sessions (3)
`dist_open_cash`, `dist_open_830`, `open_gap_ticks`
(NB: `dist_ovn_high/low` ABSENT, `ovn_range_ticks` MORT — A CREER)

### 3.5 Session high/low (4)
`dist_sess_high`, `dist_sess_low`, `sess_range_ticks`, `sess_range_atr`
(NB: IB features fragiles, fix `add_ib_atr_streaming` requis)

### 3.6 MenthorQ levels + GEX (14)
`dist_mq_call`, `dist_mq_put`, `dist_mq_hvl`,
`dist_mq_call_0dte`, `dist_mq_put_0dte`, `dist_mq_hvl_0dte`,
`dist_gex_nearest_up/dn`, `gex_cluster_count`,
`dist_blind_nearest_up/dn`, `next_wall_dist_ticks`, `next_wall_is_call`

### 3.7 VIX + macro (13)
`vix_level`, `dist_vix_hvl`, `vix_regime`, `vix_above_hvl`,
`dist_vix_call/put`, `dist_vix_call_0dte`, `dist_vix_put_0dte`,
`dist_vix_hvl_0dte`, `vix_above_hvl_0dte`,
`dist_vix_gex_nearest_up/dn`

### 3.8 Delta / Aggressor (CONVENTION SAINE) (~25)
`delta_bar`, `delta_bar_vol_norm`, `ask_bid_imbalance`,
`delta_day`, `delta_day_dir`,
`ask_pct`, `bid_pct`, `avg_trade_size`, `avg_bid_size`, `avg_ask_size`,
`large_trader_ratio`, `vol_per_sec`, `bar_duration_sec`,
`finish_strength`, `finish_delta_pct`,
`high_pullback_delta`, `low_pullback_delta`,
`poc_bar_dist`, `cvd_day`, `cvd_day_dir`, `cvd_ohlc_range`,
`diag_pos_delta`, `diag_neg_delta`, `diag_imbalance`,
`buy_vol`, `sell_vol`, `buy_sell_ratio`, `total_vol`, `delta_pct`, `ticks_count`

### 3.9 Big orders + clusters + walls (~16)
`dist_big_ask_nearest_up/dn`, `dist_big_bid_nearest_up/dn`,
`n_big_ask_t1/t2/t3`, `n_big_bid_t1/t2/t3` (t4 mort, NORMAL : pas seuils MGC),
`big_ask_cluster_20t/50t`, `big_bid_cluster_20t/50t`,
`big_ask_cluster_20t_t1`, `big_bid_cluster_20t_t1`,
`dist_cluster_nearest_up/dn`, `n_clusters_20t/50t`

### 3.10 BN (sparse mais utile) (10)
`bn_long_up`, `bn_long_dn` (35% fire, OK),
+ `bn_color_up/dn` (sparse mais signal valide),
+ `bn_absorb_ask/bid`, `bn_pressure_ask/bid`, `bn_volume_up/dn` (sparse)
(NB: `bn_score_raw/bull/bear` mortes — historique)

### 3.11 Bar shape + Extension Lines partial (4 + 2)
`bar_edge_buy`, `bar_edge_sell` (76% fire, ✅),
`dist_ext_edge_buy`, `dist_ext_edge_sell` (81% fire, ✅)
(Reste Extension Lines fragile → Python recalc Path B)

### 3.12 Swings Wyckoff base (6)
`dist_swing_high`, `dist_swing_low`, `swing_range_ticks`,
`price_vs_swing_mid`, `new_swing_high`, `new_swing_low`

### 3.13 Game Changers Dalton (12)
`open_type`, `open_zone`, `open_bias_conf`, `open_direction`,
`day_type` (figé bug — fix via Phase 2.1),
`profile_shape` (Databento ABSENT, Sierra GAGNE),
`profile_skew`, `poc_position`, `volume_imbalance`, `is_double_dist`,
`poc_separation_ticks`, `single_print_mid`, `single_print_count`,
`profile_hvn_dominant`

### 3.14 HVN/LVN session (5)
`dist_session_hvn_above/below`, `dist_session_lvn_above/below`,
`session_hvn_count`, `session_lvn_count`, `lvn_confluence_count`

### 3.15 MA + Booleans (~4 utiles)
`ma_trend`, `bool_session_early`, `vwap_triple_align`, `bool_gex_flip_zone`
(Beaucoup de booleans morts car bool_above_vwap_w/m/mq_hvl figes — Sierra n'a pas tous les flips)

### 3.16 Divergence Sierra (1 sparse)
`delta_divergence` (3.6% fire — trop pauvre, recalc Python necessaire)

**TOTAL Sierra AS-IS : 87 features stables (sans doublons)**

---

## 4. Features ABSENTES Sierra — A CREER Python

### 4.1 Module `poc_migration.py` — 2 features
- `poc_migration_dir` : signe(`dist_cur_vpoc(t)` − `dist_cur_vpoc(t-10)`)
- `ctx_poc_migration_10` : rolling slope sur 10 bars
- **Source** : `dist_cur_vpoc` Sierra

### 4.2 Module `swings_v2.py` — 6 features
- `bars_since_last_swing_high` : compteur depuis dernier swing high
- `bars_since_last_swing_low` : compteur depuis dernier swing low
- `equal_highs_detected` : detection equal highs (Wyckoff)
- `equal_lows_detected` : detection equal lows
- `liquidity_sweep_high_lag5` : sweep pattern ICT
- `liquidity_sweep_low_lag5` : sweep pattern ICT
- **Source** : `dist_swing_high/low`, `new_swing_high/low` Sierra + price action

### 4.3 Module `divergences_v2.py` — ~14 features
- `delta_div_buy` / `delta_div_sell` : rolling slope price vs delta_bar (oppose)
- `delta_div_buy_clean` / `delta_div_sell_clean` : version filtree par regime
- `delta_divergence_clean` : OR des deux
- `n_delta_div_buy_zones_active` / `n_delta_div_sell_zones_active` : zones actives
- `dist_delta_div_buy_nearest_pct` / `dist_delta_div_sell_nearest_pct` : distances
- `n_delta_div_buy_cluster_within_0_2pct` / `n_delta_div_sell_cluster_within_0_2pct`
- `retest_high_delta_div` / `retest_low_delta_div`
- `div_confluence_with_regime`, `div_at_key_level_ticks`, `div_confluence_dmp`
- `delta_div_strength`, `ctx_div_density_20`, `ctx_bars_since_div`
- **Source** : `delta_bar` + `price` Sierra rolling

### 4.4 Module `prev_levels.py` — ~16 features
- `pdh`, `pdl` : prev day high/low absolus
- `cur_pdh`, `cur_pdl` : current PDH/PDL contextuel
- `dist_pdh_pct/atr`, `dist_pdl_pct/atr`
- `cash_high`, `cash_low`, `is_new_cash_high`, `is_new_cash_low`
- `dist_cash_high_pct`, `dist_cash_low_pct`
- `open_cash`, `open_830_et`, `open_930_et`, `above_open_830/930`
- `ovn_high`, `ovn_low`, `ovn_range_ticks`
- `dist_ovn_high_pct`, `dist_ovn_low_pct`
- `ovn_broken_up`, `ovn_broken_dn`
- **Source** : OHLCV Sierra historique + tracking sessions

### 4.5 Module `sessions_fine.py` — ~25 features
- `is_in_asia`, `is_in_london`, `is_in_us_cash`, `is_in_us_after`
- `session_date`, `session_date_trading`, `session_segment`
- `asia_high`, `asia_low`, `dist_asia_high_pct`, `dist_asia_low_pct`
- `london_high`, `london_low`, `dist_london_high_pct`, `dist_london_low_pct`
- `us_high`, `us_low`, `dist_us_high_pct`, `dist_us_low_pct`
- `after_high`, `after_low`, `dist_after_high_pct`, `dist_after_low_pct`
- `asia_open`, `london_open`, `ny_open`, `after_open`
- `dist_asia_open_pct`, `dist_london_open_pct`, `dist_ny_open_pct`, `dist_after_open_pct`
- `pct_in_range`, `is_cash_session`, `is_ib_window`, `mins_et`
- **Source** : OHLCV Sierra + horloge ET (timezone)

### 4.6 Module `ctx_rolling.py` — ~25 features
- `ctx_climax_signal`, `ctx_failed_auction`
- `ctx_absorption_score_5`, `ctx_absorption_streak_5`, `ctx_instant_absorption`
- `ctx_delta_exhaustion`, `ctx_momentum_exhaustion`
- `ctx_poor_high`, `ctx_poor_low`, `ctx_excess_high_bars`, `ctx_excess_low_bars`
- `ctx_double_top_trap`
- `ctx_vol_sell_buy_ratio_5`, `ctx_vol_slope_5`, `ctx_vol_z_5`
- `ctx_finish_strength_mean_5`, `ctx_dist_vwap_velocity`, `ctx_vwap_slope_accel`
- `ctx_va_position_velocity`, `ctx_side_flip_count_10`
- `ctx_range_vs_atr_10`, `ctx_price_slope_5`
- `ctx_delta_sum_3`, `ctx_delta_sum_10`, `ctx_delta_slope_5`
- `ctx_cvd_recovery_rate`, `ctx_rvol_session`
- **Source** : rolling sur features Sierra (delta_bar, atr, vwap, finish_strength, etc.)
- **WARNING** : chaque feature avec semantique trade-decisionnelle (climax, failed_auction) MUST pass DSR > 0.5 avant prod (ml-trainer review obligatoire)

### 4.7 Module `roll_calendar.py` — 3 features
- `is_roll_day` : true si jour de roll (ES = M-Mar-Jun-Sep-Dec, NQ idem, MGC = G/J/M/Q/V/Z monthly)
- `days_since_roll` : compteur depuis dernier roll
- `roll_phase` : -1 (avant), 0 (jour roll), +1 (apres)
- **Source** : calendrier futures CME statique

### 4.8 News features — **REUTILISATION `eco_calendar.py` existant** (PAS de nouveau module)

**INFRA DEJA EN PLACE** (Jackson reminder 06/06) :
- `CORE/eco_calendar.py` (29/04/2026) — source unique ForexFactory + sessions structurelles
  - `fetch_events(force_refresh)`, `is_blocked_now()`, `is_blocked_combined()`, `next_event_block()`, `today_events()`, `get_status()`
  - Cache `DATA/CALENDAR/ff_cache.json` (TTL 6h, fallback gracieux)
  - Blackout HIGH/USD : -15min / +30min
  - Sessions : open US vol (09:15-09:45 ET), post-MOC (15:30-18:15 ET), weekend
  - Branche : Bot 1 V3, dashboard, mia_paper_trader
- `CORE/news_filter.py` (14/04/2026) — `NewsBlackoutFilter` (ancien systeme, calendrier `DATA/CALENDAR/eco_calendar.json`, branche : bn_v4_paper, bot3_v3/v4_paper)
- 2 systemes coexistent → harmonisation requise avant migration

**Plan Phase 3.7 revisé** :
1. **Choisir source unique** : `eco_calendar.py` (le plus recent, le plus complet) → deprecate `news_filter.py` (a archiver Phase 7.2)
2. **Coder wrapper feature_engineering** `eco_news_features.py` (~50 LOC) qui consomme `eco_calendar.get_status()` + `next_event_block()` et produit :
   - `is_news_5m` (bool) : evenement High USD dans 5 prochaines min
   - `is_news_15m` (bool) : evenement High USD dans 15 prochaines min
   - `mins_to_next_news` (int) : minutes avant prochaine news High USD
   - `mins_since_last_news` (int) : minutes depuis derniere news High USD
   - `is_in_blackout_eco` (bool) : `is_blocked_now()`
   - `is_in_blackout_session` (bool) : open US vol / post-MOC / weekend
   - `next_news_name` (str) : nom prochaine news (debugging)
3. **Verifier** : compat ETS (DST), source ForexFactory accessible depuis VPS
4. **Tests** : valider sur jours connus (FOMC, NFP, CPI)
5. **REVIEW code-reviewer** : pas de dupplication eco_calendar logic

**Aucune nouvelle source de calendrier** — on consomme l'existant.

### 4.9 Module `intermarket_features.py` — ~10 features (DEJA EN PLACE)
- `im_cross_delta_agreement_5`, `im_cross_delta_weighted_5`
- `im_smt_divergence`, `im_delta_day_divergence`
- `im_price_ratio_slope_10`, `im_volume_lead`
- `im_rolling_correlation_10`, `im_ltr_slope_diff`
- `im_cross_open_signal`, `im_open_type_agreement`
- **Source** : ES + NQ streams Sierra joints (compat verification needed)

### 4.10 Module `regime_engine_v2.py` — 7 features (DEJA EN PLACE)
- `regime_mode`, `regime_favor`, `regime_confidence`
- `regime_actionable`, `regime_vol`
- `regime_trend_votes`, `regime_range_votes`
- **Source** : consume features Sierra (verification compat needed)

**TOTAL features a creer Python : ~121** (dont 17 deja en place dans intermarket + regime).

**NET NOUVEAU code : ~104 features dans 8 nouveaux modules.**

---

## 5. Garde-fou SIGNE — Protocole obligatoire

### 5.1 Regle souveraine

**Toute feature signee** (delta, imbalance, slope, dir, score, vote) creee Python DOIT passer le **test cohérence direction marche** avant deploy.

### 5.2 Test sanity check (script `tools/check_feature_sign.py`)

```python
def check_feature_sign(df, feature_name, direction_threshold=60):
    """
    Verifie que la feature est COHERENTE avec direction marche.

    Critere :
    - Sur 5 jours baissiers (|change| > 500 pts ET change < 0) :
      mediane(feature) doit etre NEGATIVE (au moins 3/5 jours)
    - Sur 5 jours haussiers (|change| > 500 pts ET change > 0) :
      mediane(feature) doit etre POSITIVE (au moins 3/5 jours)
    - Convergence globale > 60%

    Si echec : BUG mapping signe → NE PAS DEPLOYER
    """
```

### 5.3 Application obligatoire

Avant `git commit` de tout module Python qui produit une feature signee :
1. Run `python tools/check_feature_sign.py <module> <feature>`
2. Si convergence < 60% → corriger le mapping signe
3. Si convergence 60-80% → flagger en WARNING dans CHANGELOG
4. Si convergence > 80% → OK

Cas particulier : si une feature est CONTRARIAN par design (e.g. `mean_reversion_score`), ajouter exemption explicite dans `tools/check_feature_sign.py:CONTRARIAN_WHITELIST` avec justification commentaire.

### 5.4 Cross-reference test

Pour chaque feature signee creee, comparer SIGNE avec :
- Sierra `delta_bar` (reference convention saine)
- Sierra `cvd_day` (reference convention saine)
- Direction prix de la barre (price(t+1) - price(t))

Si la feature signe oppose des 3 references → BUG mapping.

---

## 6. Phases 0-7 (cf TodoWrite — 74 items)

### Phase 0 — Preparation (1 jour)
- 0.1 Stop bots VPS Sim1, Sim2, Sim3 (anti-perte)
- 0.2 Commit baseline pre-migration + tag git `pre-sierra-migration`
- 0.3 Document bug delta_bar dans INCIDENT_LOG + BOT_CHANGELOG
- 0.4 Design doc (CE DOCUMENT) + checklist features
- 0.5 REVIEW Plan agent sur design doc

### Phase 1 — sierra_live_io.py (1-2 jours)
- 1.1 Code lecteur stream JSONL Sierra (tail-follow)
- 1.2 Whitelist 87 features Sierra stables + schema versioning
- 1.3 Tests unitaires (10+ tests : tail, restart, gap detection)
- 1.4 Validation empirique : 7 jours vs JSONL brut (parite 100%)
- 1.5 REVIEW code-reviewer
- 1.6 Garde-fou SIGNE : 5j baissiers + 5j haussiers, convergence > 60%

### Phase 2 — Features Sierra fragile (1 jour)
- 2.1 Fix `add_ib_atr_streaming` jamais appele (`enricher_chain.py:~508`)
- 2.2 Tests pytest day_type != 2 sur 20 jours
- 2.3 REVIEW Plan agent : impact day_type fix sur regime_engine_v2 (Bot 2 P&L risk)
- 2.4 Verifier coverage Extension Lines Python recalc (Path B)
- 2.5 Code `delta_divergence` enrichi (rolling slope)
- 2.6 Tests delta_divergence sur jours connus empiriquement
- 2.7 REVIEW market-analyst : methodologie Wyckoff/ICT correcte ?

### Phase 3 — Features ABSENTES Python (3-5 jours)
Chaque module avec sous-phases : **code → tests → review**.

- 3.1/bis/ter : `poc_migration.py`
- 3.2/bis/ter : `swings_v2.py`
- 3.3/bis/ter : `prev_levels.py`
- 3.4/bis/ter : `sessions_fine.py`
- 3.5/bis/ter : `ctx_rolling.py` (REVIEW ml-trainer DSR > 0.5)
- 3.6/bis/ter : `roll_calendar.py`
- 3.7/bis/ter : `news_calendar.py`
- 3.8/bis/ter : `intermarket_features.py` (compat)
- 3.9/bis/ter : `regime_engine_v2.py` (compat)

### Phase 4 — Validation parite dual-run (5 jours calendaires)
- 4.1 `sierra_pipeline.py` orchestrateur
- 4.2 Deploy DUAL-RUN VPS (Sierra + Databento en parallele)
- 4.3 DUAL-RUN 5 jours
- 4.4 Compare chaque feature : convergence > 95% (signed expected oppose pour delta)
- 4.5 Rapport divergence Markdown
- 4.6 REVIEW quality-auditor (5 criteres V2)
- 4.7 REVIEW schema-auditor (C++ <-> Python)

### Phase 5 — Backtests bot complets (2 jours)
- 5.1 Build dataset historique Sierra 6 mois (DMP 3.7.7)
- 5.2 REVIEW quality-auditor dataset Sierra historique
- 5.3/bis : Re-backtest Bot 1 V3 + REVIEW ml-trainer
- 5.4/bis : Re-backtest Bot 2 BN V5 + REVIEW ml-trainer (strategy alive ?)
- 5.5/bis : Re-backtest Bot 3 V4 + REVIEW ml-trainer
- 5.6 Synthese verdicts GO/NOGO par bot

### Phase 6 — Cutover production (1 jour + 24h monitor)
- 6.1 Stop databento_live_stream
- 6.2 Switch live_enricher source vers Sierra
- 6.3 Redemarrer bots avec source Sierra UNIQUEMENT
- 6.4 Monitor 24h (heartbeat, latency, signal count, trades emis)
- 6.5 J+1 valider OU rollback Databento (avant 2026-07-01)

### Phase 7 — Cleanup (0.5 jour)
- 7.1 Cancel Databento abonnement avant 2026-07-01
- 7.2 Archive code Databento mort (audit trail)
- 7.3 Update CLAUDE.md
- 7.4 Update INCIDENT_LOG + ENGINEERING_LESSONS
- 7.5 Commit final + tag `v5.0-sierra-full` + push
- 7.6 REVIEW finale code-reviewer ULTRATHINK

**TOTAL ESTIME : 9-13 jours (weekend + 1.5 semaine)**.

---

## 7. Criteres GO/NOGO par phase

| Phase | Critere GO | Action si NOGO |
|---|---|---|
| 1.4 | Parite Sierra read vs JSONL brut == 100% checksum | Fix lecteur, re-run |
| 1.6 | Garde-fou signe : convergence > 60% sur 10 jours | Stop migration, debug signe |
| 2.3 | Plan agent : impact day_type fix < 20% delta Bot 2 P&L backtest | Recalibrer regime_engine_v2 thresholds |
| 3.x.ter | Code-reviewer/market-analyst/ml-trainer : GO | Refactor + re-review |
| 3.5.ter (ctx_rolling) | DSR Lopez > 0.5 sur 6 mois | Drop feature OR refactor |
| 4.4 | Convergence Sierra vs Databento > 95% (non-signed) | Investigation, possible bug ancien Databento |
| 4.6 | Quality-auditor : 0 RED flag V2 (instrument leak, vol leak, etc.) | Drop features red, exemption explicite |
| 5.3/5.4/5.5 | ml-trainer Bot X : PSR > 0.95 ET DSR > 0.5 ET fold stability OK | Bot recalibration OR retrait |
| 5.6 | Au moins 2/3 bots passent ml-trainer | Decision pause migration |
| 6.5 | J+1 : heartbeat OK, latency < 200ms, signal count > 0 | Rollback Databento |

---

## 8. Rollback strategy

### 8.1 Avant 2026-07-01 (Databento toujours payee)

- `git checkout pre-sierra-migration` (tag Phase 0.2)
- Restart services bots avec config Databento
- Investigation cause failure
- Re-tentative migration apres fix

### 8.2 Apres 2026-07-01 (Databento annule)

**Pas de rollback Databento possible.** Sierra DOIT marcher.

Mitigation :
- Si Bot specifique ne passe pas ml-trainer Phase 5 : retirer ce bot du live, garder en backtest
- Si pipeline Sierra cassee : fallback hardcode sur dataset historique 6 mois (pas de live trade temporaire)
- Si urgence catastrophique : re-souscrire Databento ($179/mois, restauration sous 24h)

### 8.3 Decision irreversible : 2026-06-28 (J-3 avant expiration Databento)

A cette date :
- Si Phase 6 stable depuis 48h+ → annuler Databento
- Sinon → renouveler Databento 1 mois ($179 + frais) pour buffer supplementaire

---

## 9. Liens

- Audit features : `DOCS/AUDIT_SIERRA_VS_DATABENTO_20260605.md`
- Code Databento actuel : `CORE/databento_live_stream.py`
- Code enricher actuel : `CORE/enricher_chain.py`
- Schema C++ DMP : `CPP/MIA_REFACTORED/DUMPER/DMP_Transform.h`
- NautilusTrader decoder reference : https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/adapters/databento/src/decode.rs
- Bug delta_bar empirique : `verify_delta_convention_multi_jours.py`, `compare_delta_bar_per_bar.py`
- TodoWrite plan execution : 74 items (Phase 0.1 → 7.6)

---

## 10. Open questions (a clarifier avec Jackson)

1. **Faut-il stopper les bots VPS MAINTENANT (samedi soir) ?** Ils prennent des decisions inversees sur orderflow live. Risque pertes additionnelles. ATTENTE CONFIRMATION.

2. **Strategie Bot 2 BN V5 (+$887/jour recent)** : si le bug delta_bar etait expliqif des gains, est-ce la strategy reste viable avec convention fixee ? Verdict ml-trainer Phase 5.4.

3. **MGC (Gold Micro)** : Sierra dump dans `mq_levels/GC/` (mapping `SYMBOL_TO_FS_DIR`). Compat avec sierra_live_io.py ?

4. **Backfill historique 6 mois** : DMP 3.7.7 vs DMP 3.7.14 actuel. Comment garantir homogeneite ? (cf incident `feedback_bug_arr_sz_1_systemique` : pollution backfill Full Recalc).

5. **Bots Sim4 (Bot 4 actuellement live SAFE COLLECT)** : impact migration ?

---

## 11. Anti-patterns interdits

Issus de `.claude/rules/critical-tasks-review.md` et `.claude/memory/feedback_*` :

- ❌ Skip garde-fou signe pour aller plus vite
- ❌ Deploy un module Python sans test empirique sur 7 jours minimum
- ❌ Composite/score hardcode sans backtest DSR Lopez (Pattern 11 V1 + Pattern data mining)
- ❌ Re-utiliser convention Databento INVERSE par paresse
- ❌ Silent fallback si feature Sierra manquante (FAIL LOUD requis)
- ❌ Cutover prod sans dual-run 5 jours valide
- ❌ Annulation Databento avant 48h+ stable post-cutover
- ❌ Review par soi-meme (auto-validation interdite). Toujours dispatcher agent code-reviewer.

---

## Fin du design doc
