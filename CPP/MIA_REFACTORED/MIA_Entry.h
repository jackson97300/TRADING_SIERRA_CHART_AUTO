#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Entry.h — NOUVEAU PARADIGME D'ENTRÉE (remplace L1→L2→L3→L4)
// ═══════════════════════════════════════════════════════════════════════════════
//
// FONDATION: Sim Python 13/03/2026 — 20 trades, PF 1.79, WR 50%
//   Trade #1: +$186 (RVOL_ABS_SELL + EDGE_SELL + COLOR2 + VOL_CLIMAX)
//   Trade #6: +$184 (EDGE_BUY + COLOR2 + BAR_CONF + EXT_LONG_DN)
//   Trade #9: +$125 (RVOL_ABS_SELL + EDGE + COLOR2 + BAR_CONF + VA_TOP + VOL_CLIMAX)
//
// PARADIGME:
//   Zone (Extension Line / VA / MQ / GEX) → 2+ Confirmations → SLTP valid → Trade
//
// CONFIRMATIONS PROUVÉES (par ordre d'impact):
//   1. RVOL Absorption    (+0.15 conf) — Les 2 plus gros gains
//   2. Edge Zone prox     (+0.10 conf) — Dans 18/20 trades
//   3. Color Zone stackée (+0.08 conf) — Dans 18/20 trades
//   4. Bar Edge+Color     (+0.05 conf) — Dans 12/20 trades
//   5. Extension LONG     (+0.05 conf) — Momentum support/resist
//   6. VA extrême         (+0.10 conf) — Mean reversion
//   7. Double Top/Bottom  (+0.08 conf) — Retest + delta divergence
//   8. Volume Climax      (+0.10 conf) — RVOL ≥2.5x + finish contradictoire
//
// RÉTRO-COMPATIBLE: Peut coexister avec MIA_Layers.h. Appelé en parallèle
// ou en remplacement progressif.
//
// Emplacement: D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\
// Date: 2026-03-14
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"
#include "MIA_SessionPlan.h"

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES (prouvées par bench + sim)
// ═══════════════════════════════════════════════════════════════════════════════

// Distance max pour considérer un niveau comme "proche" (en ticks)
inline constexpr float ENTRY_ZONE_MAX_DIST     = 15.0f;

// Seuils de confirmation
inline constexpr float CONF_RVOL_ABSORB        = 0.15f;  // Signal le plus fort
inline constexpr float CONF_EDGE_ZONE          = 0.10f;
inline constexpr float CONF_COLOR2             = 0.08f;
inline constexpr float CONF_BAR_CONF           = 0.05f;  // bar_edge + bar_color
inline constexpr float CONF_EXT_LONG           = 0.05f;
inline constexpr float CONF_VA_EXTREME         = 0.10f;
inline constexpr float CONF_DOUBLE_TOP         = 0.08f;
inline constexpr float CONF_VOL_CLIMAX         = 0.10f;

// Seuils de confiance pour prendre le trade
inline constexpr float ENTRY_MIN_CONFIDENCE    = 0.20f;   // Minimum pour entrer
inline constexpr int   ENTRY_MIN_CONFIRMATIONS = 2;       // Au moins 2 confirmations

// Seuils BN
inline constexpr float BN_SCORE_THRESHOLD      = 0.10f;   // |bn.score| > 0.10 = signal
inline constexpr float BN_COLOR2_THRESHOLD     = 1.0f;    // Color stackée = au moins 1

// VA extrêmes (prouvé: VA TOP >80% SHORT 63% WR Asia, RANGE BOT <15% 80% WR)
inline constexpr float VA_TOP_THRESHOLD        = 0.80f;
inline constexpr float VA_BOT_THRESHOLD        = 0.20f;

// RVOL Volume Climax
inline constexpr float RVOL_CLIMAX_THRESHOLD   = 2.5f;    // rvol ≥ 2.5x


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURES
// ═══════════════════════════════════════════════════════════════════════════════

struct EntryResult {
    bool   should_enter    = false;
    int    direction       = 0;        // +1 LONG, -1 SHORT
    float  confidence      = 0.0f;     // 0.0 → 1.0
    int    n_confirmations = 0;
    char   zone_name[32]   = "";       // "EXT_EDGE_SELL", "PREV_VAL", etc.
    float  zone_dist       = 0.0f;     // Distance au niveau en ticks
    char   tags[128]       = "";       // "EDGE_SELL+COLOR2_DN+BAR_CONF+RVOL_ABS_SELL"
    char   reject_reason[64] = "";     // Si should_enter=false, pourquoi
};


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — SCANNER DE ZONES (trouver le niveau le plus proche)
// ═══════════════════════════════════════════════════════════════════════════════

struct ZoneCandidate {
    const char* name;
    float price;
    int   support_dir;   // 1=support (LONG), -1=resist (SHORT), 0=both
    int   importance;     // 1-3 (3=MAJEUR)
};

// Trouve la zone la plus proche et sa direction
inline bool ScanNearestZone(
    float current_price,
    float tick_size,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    const ExtensionLinesTracker& ext_tracker,
    float max_dist_ticks,
    // Outputs
    int& out_direction,
    float& out_dist_ticks,
    char* out_zone_name,
    int& out_importance)
{
    // Construire la liste des candidats
    ZoneCandidate candidates[30];
    int n_cands = 0;

    auto add = [&](const char* name, float price, int dir, int imp) {
        if (price > 0 && n_cands < 30) {
            candidates[n_cands++] = {name, price, dir, imp};
        }
    };

    // ── Extension Lines Edge (Tier 1 — cœur du système) ──
    if (bn.nearest_edge_rect_support > 0)
        add("EXT_EDGE_BUY", bn.nearest_edge_rect_support, 1, 3);
    if (bn.nearest_edge_rect_resist > 0)
        add("EXT_EDGE_SELL", bn.nearest_edge_rect_resist, -1, 3);

    // ── Extension Lines support/resist (BN) ──
    float sup_dist = 0, res_dist = 0;
    float nearest_sup = ext_tracker.GetNearestSupport(current_price, &sup_dist);
    float nearest_res = ext_tracker.GetNearestResist(current_price, &res_dist);
    if (nearest_sup > 0 && sup_dist < max_dist_ticks)
        add("EXT_SUPPORT", nearest_sup, 1, 2);
    if (nearest_res > 0 && res_dist < max_dist_ticks)
        add("EXT_RESIST", nearest_res, -1, 2);

    // ── MenthorQ levels ──
    add("MQ_HVL",      mq.hvl,                  0, 3);
    add("MQ_PUT",       mq.put_support,          1, 2);
    add("MQ_CALL",      mq.call_resistance,     -1, 2);
    add("MQ_PUT0D",     mq.put_support_0dte,     1, 3);
    add("MQ_CALL0D",    mq.call_resistance_0dte,-1, 3);
    add("MQ_GAMMA",     mq.gamma_wall,           0, 2);

    // ── GEX ──
    add("GEX_UP",       mq.nearest_gex_up,      -1, 2);
    add("GEX_DN",       mq.nearest_gex_dn,       1, 2);

    // ── Value Area ──
    add("CUR_VAH",      mq.vah,                 -1, 2);
    add("CUR_VAL",      mq.val,                  1, 2);
    add("PREV_VAH",     mq.prev_vah,            -1, 2);
    add("PREV_VAL",     mq.prev_val,             1, 2);
    add("PREV_VPOC",    mq.prev_vpoc,            0, 2);

    // ── VWAP ──
    add("VWAP_D",       mq.vwap,                 0, 1);
    add("VWAP+1SD",     mq.vwap_up1,            -1, 1);
    add("VWAP-1SD",     mq.vwap_dn1,             1, 1);

    // ── 1D Min/Max ──
    add("1D_MIN",       mq.day_min,              1, 2);
    add("1D_MAX",       mq.day_max,             -1, 2);

    // ── Trouver le plus proche ──
    float best_dist = 999999.0f;
    int   best_idx  = -1;

    for (int i = 0; i < n_cands; i++) {
        float dist = fabs(current_price - candidates[i].price) / tick_size;
        if (dist < best_dist && dist <= max_dist_ticks) {
            best_dist = dist;
            best_idx = i;
        }
    }

    if (best_idx < 0) return false;  // Aucun niveau proche

    const ZoneCandidate& best = candidates[best_idx];
    out_dist_ticks = best_dist;
    out_importance = best.importance;
    strncpy(out_zone_name, best.name, 31);
    out_zone_name[31] = '\0';

    // Direction basée sur le rôle du niveau
    if (best.support_dir == 1) {
        out_direction = 1;   // Support = LONG
    } else if (best.support_dir == -1) {
        out_direction = -1;  // Resist = SHORT
    } else {
        // Niveau "both" → direction basée sur la position relative
        out_direction = (current_price < best.price) ? 1 : -1;
    }

    return true;
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — COLLECTE DES CONFIRMATIONS
// ═══════════════════════════════════════════════════════════════════════════════

inline int CollectConfirmations(
    int direction,
    float current_price,
    float tick_size,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    const ExtensionLinesTracker& ext_tracker,
    float rvol_value,          // RVOL calculé par DMP (PersistentFloat)
    bool  rvol_absorb_buy,     // RVOL absorption buy signal
    bool  rvol_absorb_sell,    // RVOL absorption sell signal
    float va_position_pct,     // Position dans la VA (0-1)
    bool  inside_va,           // Inside current VA
    // Outputs
    float& out_conf_bonus,
    char* out_tags,            // Buffer pour les tags (128 chars)
    int out_tags_size)
{
    int n_conf = 0;
    out_conf_bonus = 0.0f;
    out_tags[0] = '\0';
    int tags_pos = 0;

    // Helper: ajouter un tag
    auto add_tag = [&](const char* tag) {
        int len = (int)strlen(tag);
        if (tags_pos + len + 2 < out_tags_size) {
            if (tags_pos > 0) out_tags[tags_pos++] = '+';
            memcpy(out_tags + tags_pos, tag, len);
            tags_pos += len;
            out_tags[tags_pos] = '\0';
        }
    };

    // ── 1. RVOL Absorption (signal premium — +$186 et +$125) ──
    if (direction == 1 && rvol_absorb_buy) {
        n_conf += 2;  // Vaut 2 confirmations
        out_conf_bonus += CONF_RVOL_ABSORB;
        add_tag("RVOL_ABS_BUY");
    }
    if (direction == -1 && rvol_absorb_sell) {
        n_conf += 2;
        out_conf_bonus += CONF_RVOL_ABSORB;
        add_tag("RVOL_ABS_SELL");
    }

    // ── 2. Edge Zone à proximité (dist_ext_edge) ──
    float edge_buy_dist = 0, edge_sell_dist = 0;
    if (bn.nearest_edge_rect_support > 0) {
        edge_buy_dist = fabs(current_price - bn.nearest_edge_rect_support) / tick_size;
    }
    if (bn.nearest_edge_rect_resist > 0) {
        edge_sell_dist = fabs(current_price - bn.nearest_edge_rect_resist) / tick_size;
    }
    if (direction == 1 && edge_buy_dist > 0 && edge_buy_dist <= ENTRY_ZONE_MAX_DIST) {
        n_conf++;
        out_conf_bonus += CONF_EDGE_ZONE;
        add_tag("EDGE_BUY");
    }
    if (direction == -1 && edge_sell_dist > 0 && edge_sell_dist <= ENTRY_ZONE_MAX_DIST) {
        n_conf++;
        out_conf_bonus += CONF_EDGE_ZONE;
        add_tag("EDGE_SELL");
    }

    // ── 3. Color Zone stackée (COLOR_2) ──
    if (direction == 1 && bn.color_up >= BN_COLOR2_THRESHOLD) {
        n_conf++;
        out_conf_bonus += CONF_COLOR2;
        add_tag("COLOR2_UP");
    }
    if (direction == -1 && bn.color_down >= BN_COLOR2_THRESHOLD) {
        n_conf++;
        out_conf_bonus += CONF_COLOR2;
        add_tag("COLOR2_DN");
    }

    // ── 4. Bar Edge + Bar Color (chart BARRES = double confirmation) ──
    if (direction == 1 && bn.bar_edge_buy > 0 && bn.bar_color_up > 0) {
        n_conf++;
        out_conf_bonus += CONF_BAR_CONF;
        add_tag("BAR_CONF");
    }
    if (direction == -1 && bn.bar_edge_sell > 0 && bn.bar_color_down > 0) {
        n_conf++;
        out_conf_bonus += CONF_BAR_CONF;
        add_tag("BAR_CONF");
    }

    // ── 5. Extension Line LONG (momentum support/resist) ──
    // Chercher dans l'ext_tracker les lignes proches
    int ext_long_near = ext_tracker.CountLinesWithinDistance(current_price, 20.0f,
                            direction == 1 ? 'S' : 'R');
    if (ext_long_near > 0) {
        n_conf++;
        out_conf_bonus += CONF_EXT_LONG;
        add_tag(direction == 1 ? "EXT_LONG_DN" : "EXT_LONG_UP");
    }

    // ── 6. VA extrême (mean reversion — prouvé 63% WR Asia, 80% range bot) ──
    if (inside_va) {
        if (direction == -1 && va_position_pct > VA_TOP_THRESHOLD) {
            n_conf++;
            out_conf_bonus += CONF_VA_EXTREME;
            add_tag("VA_TOP");
        }
        if (direction == 1 && va_position_pct < VA_BOT_THRESHOLD) {
            n_conf++;
            out_conf_bonus += CONF_VA_EXTREME;
            add_tag("VA_BOT");
        }
    }

    // ── 7. Volume Climax (RVOL spike ≥2.5x) ──
    if (rvol_value >= RVOL_CLIMAX_THRESHOLD) {
        n_conf++;
        out_conf_bonus += CONF_VOL_CLIMAX;
        add_tag(direction == 1 ? "VOL_CLIMAX_BUY" : "VOL_CLIMAX_SELL");
    }

    // ── 8. Retest swing high/low (Double Top/Bottom) ──
    // Détecté via BN: le prix reteste un high/low récent
    // Pour l'instant, utiliser cvd_divergence comme proxy
    if (bn.cvd_divergence) {
        n_conf++;
        out_conf_bonus += CONF_DOUBLE_TOP;
        add_tag(direction == -1 ? "DT_CVD_DIV" : "DB_CVD_DIV");
    }

    return n_conf;
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — FILTRE MOMENTUM ANTI-TREND
// ═══════════════════════════════════════════════════════════════════════════════

inline bool IsMomentumContra(
    int direction,
    float current_price,
    float price_3bars_ago,     // Prix il y a 3 barres
    float momentum_threshold)  // En points (5.0 NQ, 1.5 ES)
{
    if (price_3bars_ago <= 0) return false;

    float momentum = current_price - price_3bars_ago;

    // SHORT contre momentum haussier → SKIP
    if (direction == -1 && momentum > momentum_threshold) return true;
    // LONG contre momentum baissier → SKIP
    if (direction == 1 && momentum < -momentum_threshold) return true;

    return false;
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — POINT D'ENTRÉE PRINCIPAL
// ═══════════════════════════════════════════════════════════════════════════════
//
// Usage dans MIA_Main.cpp:
//
//   EntryResult entry = EvaluateEntry(
//       current_price, config.tick_size,
//       bn_es, mq_es, g_ext_tracker_es,
//       rvol_es, rvol_abs_buy_es, rvol_abs_sell_es,
//       va_pos_es, inside_va_es,
//       price_3bars_ago_es,
//       config, g_session_plan_es);
//
//   if (entry.should_enter) {
//       // → CalculateProtectedSLTP(entry.direction, ...)
//       // → SendBracketOrder(...)
//   }

inline EntryResult EvaluateEntry(
    float current_price,
    float tick_size,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    const ExtensionLinesTracker& ext_tracker,
    // RVOL (depuis PersistentFloat du DMP)
    float rvol_value,
    bool  rvol_absorb_buy,
    bool  rvol_absorb_sell,
    // VA position (depuis VP)
    float va_position_pct,     // 0.0-1.0
    bool  inside_va,
    // Momentum
    float price_3bars_ago,
    // Config & Plan
    const SymbolConfig& config,
    const SessionPlan& plan)
{
    EntryResult result;

    // ═══ ÉTAPE 1: TROUVER LA ZONE ═══
    int   zone_dir = 0;
    float zone_dist = 0;
    char  zone_name[32] = "";
    int   zone_imp = 0;

    bool has_zone = ScanNearestZone(
        current_price, tick_size, bn, mq, ext_tracker,
        ENTRY_ZONE_MAX_DIST,
        zone_dir, zone_dist, zone_name, zone_imp);

    if (!has_zone) {
        strncpy(result.reject_reason, "NO_ZONE", sizeof(result.reject_reason) - 1);
        return result;  // Pas de niveau proche = pas de trade
    }

    int direction = zone_dir;

    // ═══ ÉTAPE 2: VÉRIFIER BIAIS DU PLAN ═══
    // Si le plan a un biais fort et qu'on va contra → rejeter
    if (plan.plan_valid && plan.confidence >= 0.50f) {
        if (plan.bias != 0 && plan.bias != direction) {
            // Contra le plan avec haute conviction → SKIP
            strncpy(result.reject_reason, "CONTRA_PLAN", sizeof(result.reject_reason) - 1);
            return result;
        }
    }

    // ═══ ÉTAPE 3: VÉRIFIER MODULES ACTIVÉS ═══
    // Si le Session Planner désactive Range Entry et qu'on est sur un niveau VA
    if (plan.plan_valid && !plan.mod_range) {
        if (strstr(zone_name, "VAH") || strstr(zone_name, "VAL") ||
            strstr(zone_name, "VPOC")) {
            strncpy(result.reject_reason, "RANGE_OFF_BY_PLAN", sizeof(result.reject_reason) - 1);
            return result;
        }
    }

    // ═══ ÉTAPE 4: FILTRE MOMENTUM ═══
    if (IsMomentumContra(direction, current_price, price_3bars_ago,
                         config.momentum_filter_pts)) {
        strncpy(result.reject_reason, "MOMENTUM_CONTRA", sizeof(result.reject_reason) - 1);
        return result;
    }

    // ═══ ÉTAPE 5: COLLECTER LES CONFIRMATIONS ═══
    float conf_bonus = 0.0f;
    char  tags[128] = "";
    int n_conf = CollectConfirmations(
        direction, current_price, tick_size,
        bn, mq, ext_tracker,
        rvol_value, rvol_absorb_buy, rvol_absorb_sell,
        va_position_pct, inside_va,
        conf_bonus, tags, sizeof(tags));

    // ═══ ÉTAPE 6: VÉRIFIER MINIMUM CONFIRMATIONS ═══
    if (n_conf < config.min_confirmations) {
        snprintf(result.reject_reason, sizeof(result.reject_reason),
                 "CONF_%d<%d", n_conf, config.min_confirmations);
        return result;
    }

    // ═══ ÉTAPE 7: CALCULER LA CONFIANCE ═══
    // Base = importance du niveau + bonus confirmations
    float base_conf = 0.0f;
    if (zone_imp == 3) base_conf = 0.15f;       // MAJEUR
    else if (zone_imp == 2) base_conf = 0.10f;  // IMPORTANT
    else base_conf = 0.05f;                      // NORMAL

    // Proximité bonus (plus proche = plus confiant)
    float prox_bonus = (ENTRY_ZONE_MAX_DIST - zone_dist) / ENTRY_ZONE_MAX_DIST * 0.10f;

    float total_conf = base_conf + prox_bonus + conf_bonus;
    if (total_conf > 1.0f) total_conf = 1.0f;

    // ═══ ÉTAPE 8: SEUIL MINIMUM ═══
    if (total_conf < ENTRY_MIN_CONFIDENCE) {
        snprintf(result.reject_reason, sizeof(result.reject_reason),
                 "CONF_%.0f%%<%.0f%%", total_conf * 100, ENTRY_MIN_CONFIDENCE * 100);
        return result;
    }

    // ═══ TRADE VALIDÉ ═══
    result.should_enter    = true;
    result.direction       = direction;
    result.confidence      = total_conf;
    result.n_confirmations = n_conf;
    result.zone_dist       = zone_dist;
    strncpy(result.zone_name, zone_name, sizeof(result.zone_name) - 1);
    strncpy(result.tags, tags, sizeof(result.tags) - 1);

    return result;
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — LOG ENTRY DECISION
// ═══════════════════════════════════════════════════════════════════════════════

inline void LogEntryResult(SCStudyInterfaceRef sc, const EntryResult& entry,
                           const char* symbol, float price) {
    SCString msg;
    if (entry.should_enter) {
        msg.Format("[MIA_ENTRY] %s %s @ %.2f | zone=%s dist=%.0ft | conf=%.0f%% (%d) | [%s]",
                   symbol,
                   entry.direction == 1 ? "LONG" : "SHORT",
                   price,
                   entry.zone_name,
                   entry.zone_dist,
                   entry.confidence * 100.0f,
                   entry.n_confirmations,
                   entry.tags);
    } else {
        msg.Format("[MIA_ENTRY] %s REJECT @ %.2f | %s",
                   symbol, price, entry.reject_reason);
    }
    sc.AddMessageToLog(msg, 0);
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — RVOL HELPERS
// ═══════════════════════════════════════════════════════════════════════════════
//
// Le RVOL est calculé dans DMP_Main.cpp via PersistentFloat ring buffer.
// Pour le bot, on a besoin de lire ces valeurs.
//
// Slots PersistentFloat (définis dans DMP_Main.cpp):
//   170: rvol_value (ratio volume actuel / moyenne 20 barres)
//   171: rvol_zscore
//   172: rvol_buy (1.0 si spike + delta positif)
//   173: rvol_sell (1.0 si spike + delta négatif)
//   174: rvol_absorb_buy (1.0 si absorption vendeurs)
//   175: rvol_absorb_sell (1.0 si absorption acheteurs)

inline constexpr int RVOL_PERSIST_VALUE       = 170;
inline constexpr int RVOL_PERSIST_ZSCORE      = 171;
inline constexpr int RVOL_PERSIST_BUY         = 172;
inline constexpr int RVOL_PERSIST_SELL        = 173;
inline constexpr int RVOL_PERSIST_ABSORB_BUY  = 174;
inline constexpr int RVOL_PERSIST_ABSORB_SELL = 175;

// Lire les valeurs RVOL depuis PersistentFloat du DMP
// Note: ces valeurs sont écrites par DMP_Main.cpp sur le chart footprint
inline void ReadRVOL(SCStudyInterfaceRef sc, int chart_footprint,
                     float& out_rvol, bool& out_absorb_buy, bool& out_absorb_sell) {
    out_rvol = sc.GetPersistentFloat(RVOL_PERSIST_VALUE);
    out_absorb_buy = (sc.GetPersistentFloat(RVOL_PERSIST_ABSORB_BUY) >= 0.5f);
    out_absorb_sell = (sc.GetPersistentFloat(RVOL_PERSIST_ABSORB_SELL) >= 0.5f);
}
