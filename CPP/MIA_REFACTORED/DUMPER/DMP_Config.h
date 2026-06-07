#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_Config.h  —  MIA Data Dumper G3 : Configuration minimale
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rôle : Seul point d'entrée vers Sierra Chart ACSIL pour le Dumper G3.
//         Délibérément MINIMAL — le Dumper ne trade pas, il collecte.
//
//  ⚠️  NE PAS COPIER MIA_Config.h du bot ici.
//      MIA_Config.h contient BotState, BN_Data, TradeSnapshot, etc.
//      Ces structures ne concernent pas le Dumper et créent un couplage inutile.
//      Le Dumper est un système autonome : si le bot évolue, le Dumper compile
//      toujours indépendamment.
//
//  Séparation des responsabilités :
//    MIA_Config.h (bot)  → trading logic, position sizing, layers, dashboard
//    DMP_Config.h (dump) → sierrachart.h + constantes basiques du marché
//
// ═══════════════════════════════════════════════════════════════════════════════

// ── Sierra Chart ACSIL — seul include requis ─────────────────────────────────
#include "sierrachart.h"

// ── Tick sizes ────────────────────────────────────────────────────────────────
constexpr float DMP_TICK_ES = 0.25f;   // 1 tick ES = 0.25 point
constexpr float DMP_TICK_NQ = 0.25f;   // 1 tick NQ = 0.25 point

// ── Filtre Extension Lines stale (fix 24/04/2026) ─────────────────────────────
// Distance MAX autorisee (en ticks) entre prix courant et une Extension Line
// pour que la ligne soit consideree VALIDE dans DMP_ReadNearestExtensionLine.
// Au-dela, la ligne est consideree stale (duplicate apres Full Recalculation SC,
// cf https://www.sierrachart.com/SupportBoard.php?ThreadID=57101) et filtree.
//
// 500t = 125 points (ES & NQ, tick 0.25). Justification empirique sur 1034 barres
// NQ 23/04 :
//   - F1 LONG p99 = 403-419 ticks    (legitime, < 500)
//   - F3 EDGE NQ p99 AVANT fix = 1285 ticks (outliers stale, > 500)
//   - F4 COLOR NQ median AVANT fix = -4531 ticks (aberrant stale)
//   - F3 EDGE ES p99 = 117 ticks     (legitime, << 500)
// Filtre coupe les aberrations sans casser les zones legitimes.
constexpr float DMP_MAX_EXT_LINE_DIST_TICKS = 500.0f;

// ── Heures RTH (Eastern Time, en minutes depuis minuit) ───────────────────────
constexpr int DMP_RTH_START  = 9  * 60 + 30;  // 09h30 ET
constexpr int DMP_RTH_END    = 16 * 60;        // 16h00 ET
constexpr int DMP_IB_END     = 10 * 60 + 30;  // 10h30 ET (fin Initial Balance)
constexpr int DMP_OPEN_CASH  = 9  * 60 + 30;  // 09h30 ET (ouverture cash)
constexpr int DMP_OPEN_830   = 8  * 60 + 30;  // 08h30 ET (ouverture futures/rapport)

// ── Valeur sentinelle (champ absent / non calculé) ────────────────────────────
// Doit correspondre exactement à la valeur utilisée dans DMP_Reader.h / DMP_Transform.h
// FLT_MAX → converti en null dans le JSONL (pandas-compatible)
#ifndef DMP_INVALID
    #define DMP_INVALID FLT_MAX
#endif

// ── Version du schéma JSONL ───────────────────────────────────────────────────
// Incrémenté à chaque ajout/suppression de colonne pour détecter les incompatibilités
// entre fichiers .jsonl collectés à des périodes différentes.
#define DMP_SCHEMA_VERSION "3.7.21"  // Batch B4 fix range_pos collision + 7 features — 2026-06-08
// 3.7.21: B4 (2026-06-08) — Fix range_pos collision + 7 features Python -> C++
//        Phase 0 BLOQUANT : rename C++ `range_pos` -> `range_pos_va`. Python
//        `enricher_chain.py:739` ecrivait `range_pos = (close-bar_low)/(bar_high-bar_low)`
//        (bar position 0-1) qui ecrasait SILENCIEUSEMENT le C++ `range_pos`
//        (VA position 0-100). Maintenant : C++ = `range_pos_va`, Python = `range_pos`.
//        Pas de collision, pas de perte d'info.
//        Phase 1 (5 trivial) : mins_et, is_in_us_cash, dist_pdh_pct,
//          dist_pdl_pct, atr_14m_pct.
//        Phase 2 (2 easy) : cvd_session (RTH-filter cvd_day), ctx_day_type_intensity
//          (formule saine ib_broken_up/dn * |dist_vwap_d_atr|, PAS day_type pollue).
//        DROP : delta_persistence_20, big_spawn_rate_20 (rejetes walk-forward A3 :
//          rho=0.144 noise, V3 non concluant ; V4_with_cvd rho=0.199 BAT).
//        DEFER : ctx_trend_day_score (depend ctx_vol_slope_5 absent).
//        SEPARE (Python+dashboard, PAS C++ DMP) : A3_v4_with_cvd_session (strategie
//          de scoring, pas feature).
//        Schema 372 -> 379 colonnes (+7).
//
// 3.7.20: Batch B3.A F22+F12_safe+F8+F9 (25 features) — 2026-06-08
// 3.7.20: +25 features B3.A F22 PositionRange (4) + F12 BarShape SAFE (6) + F8 News (14) + F9 Roll (1) — 2026-06-08
// IMPORTANT : 4 features F12 (long_up_bar, long_dn_bar, long_dn_up_pattern,
//             long_up_dn_pattern) NON PORTEES car les equivalents Sierra natives
//             existent DEJA dans le JSONL (`bar_long_up_bar`, `bar_long_dn_bar`,
//             `bar_long_dn_up`, `bar_long_up_dn` + bonus `dist_ext_long_up/dn`
//             = Extension Lines distances). Decision Jackson 2026-06-08 00:30
//             : pattern Sierra-prime (cf B2). Verif empirique fiabilite 5j NQ
//             + 5j ES : Sierra natives 15.4% fire-rate NQ vs Python 57.6% noise
//             pure → Sierra natives PLUS SELECTIVES et propres.
// bar_no_trade : REFACTORE en formule alignee Python `delta_bar.isna()` strict
//             (DMP_F12_IsInvalid only, sans `|delta|<0.5`). Verifie 100% match
//             Python sur 9788 bars (5j NQ + 5j ES).
//        Port C++ Sierra des features Python live_enriched manquantes (25 GO PORT
//        B3.A + 4 NON-PORTEES = Sierra natives existantes JSONL + 1 DEFER
//        days_since_roll + 3 DROP : roll_phase leak instrument ks=1.0,
//        range_h_minus_lprev_ticks + range_hprev_minus_l_ticks leak vol ks_em>4).
//        Jackson rectif 2026-06-07 22:50 : discount_zone GARDE (FULL REGLES
//        "Buy the dip"). Decision 2026-06-08 00:30 : bar_no_trade REFACTORE
//        formule isna() strict (100% fiable verifie empirique) + 4 features
//        long_* utilisent les Sierra natives `bar_long_*` deja dans le JSONL.
//
//        Groupes ajoutes :
//          F22 — Position Range (4) :
//            * pct_in_range      = (close - sess_low) / (sess_high - sess_low) * 100
//            * premium_zone      = 1 si pct_in_range > 50
//            * discount_zone     = 1 si pct_in_range < 50 (Jackson rectif 22:50)
//            * position_in_range = (close - mq_1d_min) / (mq_1d_max - mq_1d_min)
//          F12 — Bar Shape SAFE (6/10 ; 4 NON-PORTEES = Sierra natives) :
//            * bar_body_pct, bar_body_ticks  (formules OHLC pures)
//            * bar_upper_wick_pct, bar_lower_wick_pct (clamp [0,3], demande Bot 4 SIM4)
//            * bar_no_trade (refactore isna() strict, 100% match Python)
//            * range_size (high - low en POINTS)
//          F12 SIERRA-PRIME mapping (deja dans JSONL, downstream utilise direct) :
//            * long_up_bar Python      → bar_long_up_bar Sierra
//            * long_dn_bar Python      → bar_long_dn_bar Sierra
//            * long_dn_up_pattern      → bar_long_dn_up Sierra (ronds jaunes)
//            * long_up_dn_pattern      → bar_long_up_dn Sierra
//            * bonus distances         : dist_ext_long_up, dist_ext_long_dn
//          F12 — Bar Shape (10) :
//            * bar_body_pct, bar_body_ticks (corps signed)
//            * bar_upper_wick_pct, bar_lower_wick_pct (wicks clamp [0, 3])
//            * bar_no_trade (boolean delta absent/0)
//            * long_up_bar, long_dn_bar (body > 2*ATR_points + sens)
//            * long_dn_up_pattern, long_up_dn_pattern (reversal shift-1)
//            * range_size (high - low POINTS)
//          F8 — News (14) :
//            * mins_et (scalar [0, 1440) DST-aware)
//            * is_news_HHMM (6 boolean event 7h15/7h30/8h30/8h45/9h00/9h30)
//            * within_news_HHMM_5m (6 boolean fenetre [tgt, tgt+5))
//            * mins_since_news, mins_to_next_news (DMP_INVALID si aucun event passe/futur)
//          F9 — Roll (1) :
//            * is_roll_day (1 toute la session si vrai roll detecte, exclus
//              manual_switch via comparaison root 2-letter)
//
//        Schema 347 -> 372 colonnes (+25 B3.A ; 4 NON-PORTEES = Sierra natives existantes).
//        Fichiers : DMP_F22_PositionRange.h (NEW), DMP_F12_BarShape.h (NEW),
//          DMP_F8_News.h (NEW), DMP_F9_Roll.h (NEW), DMP_Reader.h (+mins_et
//          + trading_day fields dans struct DMP_RawData), DMP_Transform.h
//          (+28 fields struct + 4 includes B3 + 4 appels), DMP_Writer.h
//          (n_cols 347 -> 375 + feature_families meta JSON + 28 KV serialisation
//          + 28 columns meta JSON).
//
//        PersistVars utilisees :
//          F12 : 205 (DMP_PERSIST_F12_PREV_LONG_UP)
//                206 (DMP_PERSIST_F12_PREV_LONG_DN)
//          F9  : 207 (DMP_PERSIST_F9_LAST_CONTRACT_HASH)
//                208 (DMP_PERSIST_F9_LAST_CONTRACT_ROOT)
//                209 (DMP_PERSIST_F9_ROLL_DAY_FLAG)
//                210 (DMP_PERSIST_F9_ROLL_DAY_DATE)
//          (Sans conflit : 200-202 deja delta_div, 203-204 deja B2 PDH/PDL.)
//
//        Tests : tools/test_parity_B3.py (parite Python live_enriched
//          info-only pour familles divergentes — F12 reuse formule Python
//          mais Sierra ATR peut diverger ; F22 / F8 / F9 doivent matcher
//          bit-for-bit). Sanity range checks par feature.
//
//        Conventions naming respectees :
//          _pct      : pourcentage [0, 100] ou [-100, 100]
//          _ticks    : nombre de ticks (0.25 ES/NQ)
//          is_*      : boolean event ponctuel (1 fois)
//          within_*  : boolean fenetre (plusieurs bars)
//          mins_*    : scalar minutes
//          *_zone    : boolean zone
//          *_pattern : boolean pattern shift-1
//          *_bar     : boolean morphologie bar courante
//
// 3.7.19: +38 features B2 Niveaux ABSOLUS Sierra (F4+F2+F23) — 2026-06-07
//        Port C++ Sierra des niveaux ABSOLUS pour permettre downstream
//        (bots, ML, dashboard) de reconstruire des distances normalisees
//        contre nimporte quel referentiel. Decision Jackson : Sierra prime
//        sur 3 familles (VWAP, VP, Session) car prop firms = RTH-only,
//        aucun overnight. Cf DOCS/SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md +
//        DMP_F3_DistNormalisees.h pour le bloc decision complet.
//
//        Extension B2 (2026-06-07 19:30 ET) — SD2/SD3 Weekly+Monthly
//          ajoutees apres reconfig Jackson des studies Sierra :
//            * Days to Load 30 -> 90 (charts 23 + 25)
//            * Multiplicateurs Band 1=1, 2=2, 3=3, 4=4 sur 4 etudes
//              (VWAP_WEEKLY NQ ID:43 + ES ID:23, VWAP_MONTHLY NQ ID:41 +
//               ES ID:33)
//            * Subgraphs sg3-sg6 (Band 2 et Band 3) actifs pour exposer
//              SD2 et SD3.
//          Resoud le bug pre-existant `vwap_w == vwap_m strict` detecte
//          par quality-validator (chart history < 1 mois empechait Sierra
//          de reset Monthly correctement).
//
//        Groupes ajoutes :
//          F4 — VWAP absolus (24) :
//            - Daily : vwap_d, vwap_d_sd1u/d/2u/d/3u/d (7)
//            - Weekly : vwap_w, vwap_w_sd1u/d/2u/d/3u/d (7)
//            - Monthly : vwap_m, vwap_m_sd1u/d/2u/d/3u/d (7)
//            - Previous : pvwap, pvwap_sd1u, pvwap_sd1d (3)
//          F2 — Previous + Cash + Open + OVN (8) :
//            - Previous Day H/L : pdh, pdl (snapshot session J-1 via
//              accumulateur PersistVars DMP_PERSIST_DIV_PREV_HIGH/LOW
//              dans DMP_ReadDeltaDivergenceClean au reset trading_day)
//            - Cash session : cash_high, cash_low (alias sess_high/low,
//              Sierra HH_SESSION/LL_SESSION RTH-only)
//            - Open : open_cash_lvl (09:30 ET), open_830_lvl (08:30 ET)
//            - Overnight : ovn_high_lvl, ovn_low_lvl (18:00-09:29 ET)
//          F23 — VP absolus (6) :
//            - Courant : cur_vpoc_lvl, cur_vah_lvl, cur_val_lvl
//            - Precedent : prev_vpoc_lvl, prev_vah_lvl, prev_val_lvl
//
//        Schema 309 -> 347 colonnes (+38).
//        Fichiers : DMP_F4_VWAPBands.h (NEW), DMP_F2_PrevLevels.h (NEW),
//          DMP_F23_VPAbsolus.h (NEW), DMP_Reader.h (+ prev_daily_high/low
//          + 8 fields SD2/SD3 weekly+monthly dans struct + PersistVars
//          203/204 + snapshot au reset session + 8 lectures sg3-sg6),
//          DMP_Transform.h (+38 fields struct + 3 appels helpers + CSV
//          header), DMP_Writer.h (+38 serialisation + meta + sierra_prime
//          + n_columns 347).
//
//        Tests : tools/test_parity_B2.py compare les niveaux Sierra vs
//          Python live_enriched. DIVERGENCE ATTENDUE sur VWAP/VP/Session
//          (3 familles ou Sierra prime, ancrages/algos differents). Test
//          verifie : (1) valeurs Sierra dans plage realiste, (2) signe
//          correct vs close. Pas de parite bit-for-bit attendue.
//
// 3.7.18: +37 features F3 Distances normalisees _pct (Batch B1) — 2026-06-07
//        Port C++ Sierra des features dist_*_pct Python live_enriched.
//        Formule : pct = (level - close) / close * 100 (signed, sans clamp).
//        Pendant : CORE/phase_b_helpers.py:1063-1093 _dist().
//
//        Groupes ajoutes :
//          A. VWAP _pct (13)  : daily SD0/1/2/3 + weekly SD0/1 + monthly SD0/1
//          B. VP _pct (6)     : VPOC/VAH/VAL courant + J-1
//          C. Session _pct (2): sess_high/low
//          D. MenthorQ _pct (6): call/put/hvl x {normal, 0DTE}
//          E. 1D Extremes _pct (2): mq_1d_max/min
//          F. Zones nearest _pct (8) : long_up/dn, color_up/dn, edge_buy/sell,
//             gex_nearest_up/dn (methode Extension Lines, divergence Python)
//
//        Schema 272 -> 309 colonnes (+37).
//        Fichiers : DMP_F3_DistNormalisees.h (NEW), DMP_Transform.h (+37 fields
//          struct + appel + CSV header), DMP_Writer.h (+37 serialisation +
//          meta + n_columns 309).
//        Pendant Python live_enriched conserve pour fallback transition.
//        Test parite : tools/test_parity_B1.py (29 features groupes A-E
//          parite bit-for-bit attendue ; 8 features groupe F divergence
//          methode documentee — semantique preservee).
// 3.7.17: CLAMP ATR 5.0 -> 20.0 align Python tolerance — 2026-06-07
//        J1 plan Option A solution long terme (post ml-trainer NOGO 4/10).
//        Decouverte critique audit V3 : DMP_ATR_CLIP=5.0f saturait 70% des
//        bars sur Python pipeline non-clampe -> representation hybride
//        train-serve skew. Alignement obligatoire pour pivot Sierra-source +
//        Python-formules. Cf DOCS/SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md note
//        gouvernance + DOCS/DIVERGENCES_METHODE_INVESTIGATION.md.
//        Aucun changement de colonnes (272 inchangees). Comportemental.
//        Re-entrainer LightGBM v4 obligatoire post-deploy (recommendation
//        ml-trainer).
// NOTE 06/06 nuit : Phase 2.1bis Niveau 1 (day_type null Asia/London) ANNULE
//        par Jackson. Revert vers comportement 3.7.15. Voie retenue :
//        re-calibrer seuils Dalton C++ sur dataset etendu 133 jours
//        (live_enriched + Sierra) au lieu de masquer Asia/London.
//        Reprise Phase 2.1.C : backtest-runner avec n=133 jours.
// 3.7.15: +4 features T&S aggregates depuis VAP — 2026-06-06
//         max_ask_vol_in_bar, max_bid_vol_in_bar, p99_trade_size_proxy,
//         large_trader_max_size. Comble le "trou T&S" Sierra (pas de trades
//         individuels comme Databento). Lecture depuis s_VolumeAtPriceV2
//         dans DMP_ReadFPBS() boucle scan VAP existante (pas de nouveau scan,
//         accumulation in-place).
//         Migration full Sierra elimine dependance Databento (bug delta_bar
//         inverse). Schema 268 → 272 colonnes.
//         Fichiers : DMP_Reader.h (+4 fields fpbs_* + accumulation boucle VAP),
//         DMP_Transform.h (+4 fields G6C + mapping + CSV header),
//         DMP_Writer.h (+serialisation JSONL + meta n_columns 272).
// 3.7.14: +atr_14m ATR 14-barres 1-min intraday — 24/04/2026 (rollback aussi
//         d'une tentative ExtensionLineCount qui saturait ES 100% / NQ 0%)
// 3.3.0: BN sg2→sg0 (color/absorb/long per-bar) + 6 colonnes big order cluster
// 3.4.0: +8 colonnes range trading (range_pos, momentum, touches, bars_in_va)
// 3.5.0: Big Orders par seuil (n_big_ask/bid → n_big_ask/bid_t1..t4) +6 cols
// 3.5.1: Cluster 20t par tier (big_ask/bid_cluster_20t_t1..t4) +8 cols
// 3.5.2: COLOR UP/DN séparés type 1 (pullback) et type 2 (double stacké) +4 cols
//        + SECTION 6C retest tracking + SECTION 6D edge zone tracker
// 3.6.0: +6 RVOL (rvol, rvol_zscore, rvol_buy/sell, rvol_absorb_buy/sell)
//        + DST fix + VWAP W/M v6 fix + ES VOLUME UP/DN + Poor Highs/Lows
// 3.7.0: +8 VIX Gamma étendu (dist_vix_call/put, 0DTE call/put/hvl, GEX nearest)
//        → SCELLÉ 18/03/2026
// 3.7.1: +2 BAR OHLC (bar_high, bar_low) — 27/03/2026
//        Nécessaire pour labeling TP/SL exact dans le pipeline ML
// 3.7.2: +2 VWAP SD3 (dist_vwap_d_sd3u, dist_vwap_d_sd3d) — 28/03/2026
//        sg5/sg6 Chart 26/27 (confirmé chart JSON scan 28/03/2026)
// 3.7.3: +4 Cluster Volume features — 13/04/2026
//        dist_cluster_nearest_up, dist_cluster_nearest_dn, n_clusters_20t, n_clusters_50t
//        Lecture directe VAP cells (seuil total volume ES=500 / NQ=50) via
//        DMP_ReadVolumeClustersFromVAP (pattern identique a DMP_ReadBigOrdersFromVAP).
//        Remplace l'ancien code DMP_ReadRotation::cluster_prices (bug 26 jours).
// 3.7.5: Fix delta_divergence via Daily OHLC semantics — 17/04/2026
//        Remplacement DMP_ReadExtensionLineCount (100% a 1 permanent sur
//        marche trending) par DMP_ReadDeltaDivergenceClean (calcul C++ custom
//        avec PersistVars). Formule SC identifiee (ID33 = Daily OHLC) :
//          BUY  : AND(daily_low  < daily_low[-1],  delta_bar >= 0)
//          SELL : AND(daily_high > daily_high[-1], delta_bar <= 0)
//        Fire rate empirique 20260416 : 0.4% NQ / 0.2% ES (vs 100% avant fix).
//        Aucun changement de colonnes. Python equivalent = rolling_features.py
//        delta_divergence_clean (match exact avec 2 triangles NQ 06:07/06:10 UTC).
//
// 3.7.4: PosInRange sentinel -1 -> DMP_INVALID (null JSONL) — 16/04/2026
//        Changement SEMANTIQUE (pas de colonne ajoutee/retiree).
//        Avant: va_position_pct, ib_position_pct valaient -1 hors range.
//        Apres: null (DMP_INVALID -> "null" via DMP_WR_IsInvalid).
//        Impact empirique v3 parquet: 66-98% des lignes ES avaient -1 polluant
//        le ML. Fix DMP_Transform.h:531 PosInRange + 5 callers inside_*_va.
//        Pipeline Python synchronise (rule_engine, dmp_validator, ib_recalc).
//        Fix ATR x4: lignes de code corrigees dans la meme nuit (3 deploys C++).
//
// 3.7.14: +atr_14m ATR 14-barres 1-min intraday — 24/04/2026
//        Contexte : audit ATR revele que `atr` dans le JSONL est en fait `atr_daily`
//          (lu depuis chart DAILY). Nom ambigu. VolatilitySpikeGate dans BOT/bot_main.py
//          calcule `bar_range/atr` avec ratio toujours < 0.1 → gate jamais declenchee
//          (bug safety net critique quand bot ira live).
//        Fix : nouveau champ `atr_14m` calcule en C++ (True Range rolling 14 barres
//          1-min depuis chart BARRES 23/25). En ticks. Permet :
//            1. VolatilitySpikeGate de detecter spike intraday (bar_range/atr_14m)
//            2. SLTPEngine bornes ATR-based dynamiques (backlog P2 reporte)
//            3. ML features avec ATR intraday (vs atr daily)
//        `atr` (daily) conserve pour retrocompat features `dist_X_atr` (normalisation
//          a echelle journaliere, intentionnel).
//        Schema 267 → 268 colonnes (ajout 1 feature).
//        Fichiers : DMP_Reader.h (+helper DMP_Calc_ATR_14m + field), DMP_Transform.h
//          (+field f.atr_14m), DMP_Writer.h (+serialisation + meta n_columns 268).
//
// 3.7.13: Fix cluster threshold dynamique via GetChartStudyInputInt — 24/04/2026
//        Bug empirique : `dist_cluster_nearest_up` ES fire 2.2% (91% null) sur
//        1210 barres 23/04. NQ cluster 34% fire. Cause racine : seuils C++
//        hardcoded (ES=500/NQ=50) desynchronises des seuils reels de l'etude SC
//        CLUSTER VOLUME (ES=250/NQ=20 - confirmé Jackson 24/04).
//        Fix : sc.GetChartStudyInputInt(chart, CLUSTER, 1, threshold) lit
//        dynamiquement In:2 "Volume Threshold" de l'etude SC ID:10 (ES) / ID:12 (NQ).
//        Chemin 2 propre (auto-sync avec SC) validé par Jackson.
//        Fallback : valeurs connues ES=250/NQ=20 si lecture API echoue.
//        Impact attendu : fire rate ES `n_clusters_20t` 10% → ~40-50%.
//        Aucun changement colonnes (267). File : DMP_Reader.h:1749-1770.
//
// 3.7.12: Fix F2 LONG DN_UP / UP_DN reversal via DMP_ReadBN_Event — 24/04/2026
//        Bug empirique ES 0% fire sur 1210 barres 23/04 (feature morte).
//        NQ fire 1.8-2.7% par chance de timing SC (instable).
//        Cause racine : formule etude utilise [1] (barre future) :
//          AND(O<C[-1], H[-1]>L+9t, O[1]>C, H[1]>L+9t, H[1]>H[-1])
//        Sur sz-1 (live), [1] n'existe pas → formule=FALSE → sg0=0 permanent.
//        Fix : lire sz-2 (derniere barre FERMEE) via DMP_ReadBN_Event. A cet
//        index, [1] = sz-1 (barre maintenant live) existe → formule evaluable.
//        Bug identique a celui documente pour COLOR UP/DN (fix 09/03/2026).
//        Fichier : DMP_Reader.h:1784-1787. Aucun changement colonne (267).
//
// 3.7.11: bool_near_level renforce (filtre confluence bar_edge) — 24/04/2026
//        Contexte : bar_edge_buy/sell NQ saturent 84% (vs ES 12%). Jackson tradingue
//        manuellement seulement les signaux EDGE proches d'un niveau majeur. Permet
//        filtre `bar_edge_* AND bool_near_level` cote bot → saturation 84% → ~20%.
//        Modifs DMP_Transform.h :
//          (1) DMP_PROXIMITY_ES : 20 → 10 ticks (2.5 pts, 0.5 ATR ES)
//          (2) DMP_PROXIMITY_NQ : 30 → 10 ticks (2.5 pts, 0.7 ATR NQ)
//          (3) CalcBooleans : 12 → 23 niveaux majeurs checkes
//              +cur_vah, +cur_val, +vwap_d, +vwap_w, +vwap_m, +ib_high, +ib_low,
//              +sess_high, +sess_low, +swing_high, +swing_low (11 nouveaux niveaux)
//        Justification empirique 10 barres NQ 24/04 17:13-17:22 :
//          - 2 signaux vraiment pertinents a -4t et -5t du CUR_VPOC (retest precis)
//          - 30t capturait 50% des barres (3/5 bruit a VPOC +/-12/+23/-29t)
//          - 10t cible = 20% fire effectif (aligne ES naturel)
//        Aucun changement schema colonnes (267 inchanges). Comportemental.
//
// 3.7.10: Fix DMP_ReadNearestExtensionLine max_dist filtre — 24/04/2026
//        Bug detecte empiriquement sur 1034 barres NQ live 23/04 :
//          dist_ext_color_up/dn NQ = -4531/-4554 ticks (MEDIAN sur 100% des barres)
//          dist_ext_edge_buy/sell NQ p99 = 1285/1470 ticks (outliers extremes)
//        Cause racine : SC duplique les Extension Lines a chaque Full Recalculation
//          (gotcha officiel : ThreadID=57101 "each recalculation duplicates the
//          lineuntilfuture"). DMP_ReadNearestExtensionLine retournait la ligne la
//          plus proche SANS filtre de distance max → lignes historiques stale (ex:
//          COLOR UP jamais retestee a -1133 points du prix) retournees en permanence.
//        Fix : constante MAX_EXTENSION_LINE_DIST_TICKS=500 (=125 points ES/NQ)
//          skip lignes > max_dist dans la boucle scan. Legitimite preservee :
//          F1 LONG p99=420t < 500, F3 EDGE ES p99=117t < 500, COLOR ES med=-303t < 500.
//        Aucun changement schema (comportemental). Impact : features stale passent
//          a null (DMP_INVALID → "nan" JSONL) au lieu de valeurs aberrantes.
//
// 3.7.9: +dist_mq_hvl_0dte (distance HVL 0DTE en ticks) — 24/04/2026
//        Bug detecte par Jackson empiriquement : HVL 0DTE visible chart (~26925)
//        est AVEUGLE pour le bot car DMP ne dump PAS dist_mq_hvl_0dte dans JSONL.
//        Le DMP Reader lit deja mq_hvl_0dte (sg7 MQ_GAMMA) depuis 31/03 mais
//        Transform.h expose uniquement call/put 0DTE. Le HVL 0DTE est utilise
//        UNIQUEMENT comme FALLBACK pour call/put 0DTE quand superposes (fix 31/03).
//        Cas observe 23/04 : 3 niveaux 0DTE DISTINCTS (Call=27150, HVL=26925, Put=26700)
//        → fallback ne se declenche pas → HVL 0DTE invisible bot.
//        Fix : +1 feature dist_mq_hvl_0dte (266 → 267 cols), 3 modifs C++ minimales.
//        Impact edge Jackson : HVL 0DTE = niveau cle pour confluence zones BN.
//        Reviewed by code-reviewer (audit avant deploy).
//
// 3.7.8: Fix ib_position_pct guard ib_complete — 20/04/2026
//        Bug detecte par schema-auditor : pendant formation IB (9:30-10:30 ET),
//        ib_position_pct calcule sur range PARTIEL malgre ib_complete=0.
//        ~61 barres/jour (ES et NQ) avec ambiguite ML : ib_complete=0 + ib_position_pct=0.47.
//        Fix : DMP_Transform.h:848 guard `r.ib_complete ? PosInRange(...) : DMP_INVALID`.
//        Synchronise CORE/ib_recalc.py:197 (meme guard Python).
//        Changement SEMANTIQUE (pas colonne ajoutee). Post-fix : ib_position_pct null
//        tant que IB pas complete. Coherent avec ib_complete/ib_broken_*.
//        Validator V2.16 detecte < 1% post-deploy (4.4% pre-fix sur 17/04 empirique).
//        Reviewed by schema-auditor + 2 code-reviewer agents.
//
// 3.7.7: CORRECTION fix 3.7.6 : arr[sz-2] au lieu de arr[sz-1] — 17/04/2026
//        Audit empirique post-deploy 3.7.6 : 650 barres ES+NQ fresh = 0.0% color
//        PARTOUT (fix sz-1 ne fire jamais). Cause identifiee : les etudes
//        [AV] COLOR UP/DN utilisent O[1] (barre suivante) dans leur formule
//        ACSIL. Sur arr[sz-1] (derniere barre = live en formation), [1] n'existe
//        pas encore -> formule retourne 0 -> fire impossible.
//        Fix : passer a arr[sz-2] (avant-derniere barre fermee) ou [1] existe.
//        Divergence volontaire avec DMP_ReadBN_Trigger (sz-1) qui reste OK
//        pour les etudes sans [1] dans la formule (absorb, long, bar_edge).
//        Attendu post-fix : color events 2-8% = coherent setup visuel Jackson.
//
// 3.7.6: Fix Battle Navale features events via SG0 direct — 18/04/2026
//        Remplacement DMP_ReadExtensionLineCount (sature 99% sur trending) et
//        DMP_ReadBN_SumOfAlerts (vide/non populate pour rotation) par
//        DMP_ReadBN_Event (lit arr[sz-1] de sg0 Color Bar = evenement ponctuel).
//        Pattern identique a DMP_ReadBN_Trigger existant (sz-1) mais retourne
//        bool 0/1 au lieu de valeur raw (prix).
//        Features corrigees (12 appels) :
//          bn_color_up/dn, bn_color_up_2/dn_2 (FP chart) [saturees 99%]
//          bn_double_ask/bid (ES FP) [saturees]
//          bn_triple_ask/bid (NQ FP) [0% avant fix - config etude a verifier]
//          bar_color_up/dn (BARRES chart) [saturees 90%]
//          bar_pressure_ask/bid (BARRES chart) [saturees 58-63% NQ]
//          rotation_up/dn_signal (FP chart) [0% avant - SumOfAlerts vide]
//        Distribution attendue NQ 15/04 post-fix : ~2-8% bars (vs 90% avant).
//        IMPORTANT : parquet v3 devient HETEROGENE au 18/04. Donnees pre-3.7.6
//        ont BN satures (distribution incompatible), post-3.7.6 events propres.
//        -> Rebuild dataset obligatoire avec coupe au 18/04 avant re-training ML.
//        Aucun changement de colonnes (noms et semantique preserves au niveau
//        schema, seulement la distribution change = event au lieu de saturation).
//        Captures SC Jackson 18/04/2026 : COLOR UP ID:26, TRIPLE ASK ID:37,
//        ROTATION UP ID:21 (toutes "Color Bar Based On Alert Condition").

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Config.h
// ═══════════════════════════════════════════════════════════════════════════════
