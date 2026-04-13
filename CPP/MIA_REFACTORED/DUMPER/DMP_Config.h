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
#define DMP_SCHEMA_VERSION "3.7.3"   // G3-Unifier — 266 colonnes
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

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Config.h
// ═══════════════════════════════════════════════════════════════════════════════
