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
#define DMP_SCHEMA_VERSION "3.7.8"   // Fix ib_position_pct guard ib_complete — 266 colonnes
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
