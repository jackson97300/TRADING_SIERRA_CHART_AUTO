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
#define DMP_SCHEMA_VERSION "3.0.0"   // G3-Unifier — 168 colonnes

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Config.h
// ═══════════════════════════════════════════════════════════════════════════════
