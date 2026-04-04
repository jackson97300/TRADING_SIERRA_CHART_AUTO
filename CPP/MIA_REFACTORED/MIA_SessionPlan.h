#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_SessionPlan.h — Session Planner (C++ temps réel)
// ═══════════════════════════════════════════════════════════════════════════════
//
// PHILOSOPHIE
// -----------
// Le trader allume ses charts, analyse la structure, diagnostique le type de
// journée, identifie les targets, puis attend le bon setup. Ce module reproduit
// ce rituel en C++ temps réel.
//
// Le SessionPlan tourne 1 SEULE FOIS au début de chaque session et produit
// un plan qui CADRE tout le reste du bot (filtres, modules, targets, risk).
//
// PARADIGME: Target → Biais → Entry (proactif avec un plan)
//   Ancien:  L1 → L2 → L3 → L4 (réactif barre par barre)
//
// SESSIONS (heure Paris CET / heure ET)
// ──────────────────────────────────────
//   01h-03h Paris / 20h-22h ET   ASIA IB        ◀ Range institutionnel
//   03h-07h Paris / 22h-02h ET   ASIA QUIET     Volume faible
//   07h-08h15 Paris              LONDON TRANS    ⚠️ NO TRADE
//   08h15-09h30                  LONDON ACTIVE   ◀ Trading
//   09h30-09h45                  US TRANS        ⚠️ NO TRADE
//   09h45-10h30                  US IB FORMING   ◀ Observer Open Type
//   10h30-12h                    US ACTIVE       ◀ Meilleure session
//   12h-14h                      MID AM          Mean reversion
//   14h-16h                      US PM           MOC flows
//
// DONNÉES PROUVÉES PAR LE SIM (13/03/2026)
// ─────────────────────────────────────────
//   20 trades NQ+ES, PF 1.79, WR 50%
//   RVOL Absorption = signal le plus fort (+$186, +$125)
//   Edge+Color+BarConf = combo minimum pour entrer
//   Pre_Open = piège (29% WR) → exclu
//   Per-session max 5 trades → distribue London + US
//
// Emplacement: D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\
// Date: 2026-03-13
// Dépend de: MIA_Config.h, MIA_DataReader.h (DmpBar)
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — ÉNUMÉRATIONS
// ═══════════════════════════════════════════════════════════════════════════════

enum SessionPhase {
    PHASE_ASIA_WARMUP    = 0,   // 19h-20h ET  (00h-01h Paris)
    PHASE_ASIA_IB        = 1,   // 20h-22h ET  (01h-03h Paris)  ◀ Capturer range
    PHASE_ASIA_QUIET     = 2,   // 22h-02h ET  (03h-07h Paris)
    PHASE_PRE_LONDON     = 3,   // 02h-02h30   (07h-07h30 Paris)
    PHASE_LONDON_TRANS   = 4,   // 02h30-03h15 (07h30-08h15)  ⚠️ NO TRADE
    PHASE_LONDON_ACTIVE  = 5,   // 03h15-04h30 (08h15-09h30)
    PHASE_US_TRANS       = 6,   // 09h30-09h45 (15h30-15h45)  ⚠️ NO TRADE
    PHASE_US_IB_FORMING  = 7,   // 09h45-10h30 (15h45-16h30)  ◀ Observer OT
    PHASE_US_ACTIVE      = 8,   // 10h30-12h   (16h30-18h)    ◀ MEILLEURE
    PHASE_MID_AM         = 9,   // 12h-14h     (18h-20h)
    PHASE_US_PM          = 10,  // 14h-16h     (20h-22h)
    PHASE_UNKNOWN        = 99,
};

enum PlanRegime {
    PLAN_UNKNOWN    = 0,
    PLAN_RANGE      = 1,   // Double distribution → jouer extrêmes
    PLAN_TREND_UP   = 2,   // Profile B + OD → pullbacks LONG
    PLAN_TREND_DN   = 3,   // Profile P + OD → pullbacks SHORT
    PLAN_ROTATION   = 4,   // Symétrique → mean reversion douce
    PLAN_BREAKOUT   = 5,   // IB cassée → expansion
};

enum ProfileShape {
    SHAPE_UNKNOWN = 0,
    SHAPE_B       = 1,   // Distribution basse → biais LONG
    SHAPE_P       = 2,   // Distribution haute → biais SHORT
    SHAPE_D       = 3,   // Double distribution → RANGE
    SHAPE_SYM     = 4,   // Symétrique → ROTATION
};


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURES
// ═══════════════════════════════════════════════════════════════════════════════

// ── IB Range (Asia, London, US) ──────────────────────────────────────────────
struct IBRange {
    float high       = 0.0f;
    float low        = 0.0f;
    float mid        = 0.0f;
    float range_ticks= 0.0f;
    bool  valid      = false;
    bool  broken_up  = false;  // Prix a cassé au-dessus
    bool  broken_dn  = false;  // Prix a cassé en-dessous
    bool  is_narrow  = false;  // Range < 30% ATR → breakout probable
    bool  is_wide    = false;  // Range > 70% ATR → direction établie

    int direction_bias() const {
        if (broken_up && !broken_dn) return +1;
        if (broken_dn && !broken_up) return -1;
        return 0;
    }

    void reset() {
        high = low = mid = range_ticks = 0.0f;
        valid = broken_up = broken_dn = is_narrow = is_wide = false;
    }
};

// ── Target structurel (aimant) ───────────────────────────────────────────────
struct PlanTarget {
    char  name[24]     = "";     // Ex: "PREV_VPOC", "PUT_0DTE"
    float price        = 0.0f;
    float dist_ticks   = 0.0f;   // Distance actuelle (positif = au-dessus)
    float conviction   = 0.0f;   // 0.0-1.0
    int   tier         = 0;      // 1=PRIMARY, 2=SECONDARY, 3=DEFENSIVE
};

// ── Session Plan (produit 1x/session) ────────────────────────────────────────
struct SessionPlan {
    // ── Identité ──
    SessionPhase current_phase = PHASE_UNKNOWN;
    bool         plan_valid    = false;       // Plan calculé avec succès

    // ── Diagnostic ──
    PlanRegime   regime        = PLAN_UNKNOWN;
    int          bias          = 0;           // +1=LONG, -1=SHORT, 0=NEUTRE
    float        confidence    = 0.0f;        // 0.0 → 1.0
    ProfileShape prev_shape   = SHAPE_UNKNOWN;

    // ── IB Stack ──
    IBRange      asia_ib;
    IBRange      london_ib;
    IBRange      us_ib;

    // ── Targets (max 5 up + 5 down) ──
    PlanTarget   targets_up[5];
    int          n_targets_up  = 0;
    PlanTarget   targets_dn[5];
    int          n_targets_dn  = 0;
    PlanTarget   primary_target;
    bool         has_primary   = false;

    // ── Modules activés ──
    bool         mod_rvol      = true;   // RVOL Absorption trigger
    bool         mod_range     = true;   // Range Entry (VA extrêmes)
    bool         mod_double_top= true;   // Double Top/Bottom
    bool         mod_exhaustion= true;   // Exhaustion multi-barres
    bool         mod_zone      = true;   // Zone classique (niveaux+biais)

    // ── Risk ──
    float        sizing_factor = 1.0f;   // 1.0=normal, 1.25=high conv, 0.75=low
    int          max_trades_session = 5;
    int          max_trades_day     = 16;
    bool         sl_tight      = false;  // true en RANGE (SL serré)
    bool         trailing_on   = true;   // false en RANGE strict

    // ── No-trade ──
    bool         is_no_trade(int time_et) const {
        // London transition: 02h30-03h15 ET
        if (time_et >= 150 && time_et < 195) return true;
        // US transition: 09h30-09h45 ET
        if (time_et >= 570 && time_et < 585) return true;
        return false;
    }

    // ── Phase autorisée pour trader ──
    bool         is_trade_phase(SessionPhase phase) const {
        switch (phase) {
            case PHASE_LONDON_ACTIVE:
            case PHASE_US_ACTIVE:
            case PHASE_MID_AM:
            case PHASE_US_PM:
                return true;
            case PHASE_US_IB_FORMING:  // Open_30m — PF 1.53 prouvé
                return true;
            default:
                return false;  // Asia, Pre_London, transitions = pas de trade
        }
    }

    // ── IB active (la plus récente valide) ──
    const IBRange& active_ib() const {
        if (us_ib.valid)     return us_ib;
        if (london_ib.valid) return london_ib;
        if (asia_ib.valid)   return asia_ib;
        static IBRange empty;
        return empty;
    }

    // ── Target pour une direction ──
    const PlanTarget* target_for(int direction) const {
        if (direction > 0 && n_targets_up > 0) return &targets_up[0];
        if (direction < 0 && n_targets_dn > 0) return &targets_dn[0];
        return nullptr;
    }

    // ── Log ──
    void log(SCStudyInterfaceRef sc) const {
        SCString msg;
        msg.Format("SessionPlan: regime=%d bias=%d conf=%.0f%% shape=%d "
                    "AsiaIB=%.0ft%s%s modules=%c%c%c%c%c sizing=%.2f",
                    regime, bias, confidence * 100.0f, prev_shape,
                    asia_ib.range_ticks,
                    asia_ib.broken_up ? " BROKE_UP" : "",
                    asia_ib.broken_dn ? " BROKE_DN" : "",
                    mod_rvol ? 'R' : '-',
                    mod_range ? 'A' : '-',
                    mod_double_top ? 'D' : '-',
                    mod_exhaustion ? 'E' : '-',
                    mod_zone ? 'Z' : '-',
                    sizing_factor);
        sc.AddMessageToLog(msg, 0);
    }
};


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// ── Seuils Asia IB ──
inline constexpr int   ASIA_IB_START_ET       = 20 * 60;       // 20h00 ET
inline constexpr int   ASIA_IB_END_ET         = 22 * 60;       // 22h00 ET
inline constexpr float ASIA_IB_NARROW_PCT     = 0.30f;         // < 30% ATR
inline constexpr float ASIA_IB_WIDE_PCT       = 0.70f;         // > 70% ATR

// ── Seuils London IB ──
inline constexpr int   LONDON_IB_START_ET     = 3 * 60 + 15;   // 03h15 ET
inline constexpr int   LONDON_IB_END_ET       = 4 * 60 + 15;   // 04h15 ET (1h)

// ── Seuils US IB (déjà dans DmpBar via ib_high/ib_low) ──
inline constexpr int   US_IB_START_ET         = 9 * 60 + 30;   // 09h30 ET
inline constexpr int   US_IB_END_ET           = 10 * 60 + 30;  // 10h30 ET

// ── Seuils Profile ──
inline constexpr float POC_HIGH_THRESHOLD     = 0.65f;  // POC > 65% range → P shape
inline constexpr float POC_LOW_THRESHOLD      = 0.35f;  // POC < 35% range → B shape

// ── Seuils Targets ──
inline constexpr float TARGET_MAX_DIST_TICKS  = 200.0f;
inline constexpr float TARGET_MIN_DIST_TICKS  = 15.0f;

// ── Seuils Conviction ──
inline constexpr float HIGH_CONVICTION        = 0.70f;  // Sizing ×1.25
inline constexpr float LOW_CONVICTION         = 0.40f;  // Sizing ×0.75


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — DÉTECTION DE PHASE
// ═══════════════════════════════════════════════════════════════════════════════

inline SessionPhase DetectPhase(int time_et) {
    // time_et = hour * 60 + minute (ex: 9h30 = 570)
    if (time_et >= 19 * 60       && time_et < ASIA_IB_START_ET) return PHASE_ASIA_WARMUP;
    if (time_et >= ASIA_IB_START_ET && time_et < ASIA_IB_END_ET) return PHASE_ASIA_IB;

    // Wrap midnight: 22h-02h = Asia Quiet
    if (time_et >= ASIA_IB_END_ET || time_et < 2 * 60)          return PHASE_ASIA_QUIET;

    if (time_et >= 2 * 60        && time_et < 2 * 60 + 30)      return PHASE_PRE_LONDON;
    if (time_et >= 2 * 60 + 30   && time_et < 3 * 60 + 15)      return PHASE_LONDON_TRANS;
    if (time_et >= 3 * 60 + 15   && time_et < 4 * 60 + 30)      return PHASE_LONDON_ACTIVE;

    // 4h30-9h30 = pas de phase définie (extended London / Pre-US)
    if (time_et >= 4 * 60 + 30   && time_et < 9 * 60 + 30)      return PHASE_LONDON_ACTIVE;

    if (time_et >= 9 * 60 + 30   && time_et < 9 * 60 + 45)      return PHASE_US_TRANS;
    if (time_et >= 9 * 60 + 45   && time_et < 10 * 60 + 30)     return PHASE_US_IB_FORMING;
    if (time_et >= 10 * 60 + 30  && time_et < 12 * 60)          return PHASE_US_ACTIVE;
    if (time_et >= 12 * 60       && time_et < 14 * 60)          return PHASE_MID_AM;
    if (time_et >= 14 * 60       && time_et < 16 * 60)          return PHASE_US_PM;

    return PHASE_UNKNOWN;
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — CALCUL ASIA IB (appeler chaque barre pendant 20h-22h ET)
// ═══════════════════════════════════════════════════════════════════════════════

inline void UpdateAsiaIB(IBRange& ib, float price_high, float price_low,
                         float atr, float tick_size) {
    if (price_high <= 0 || price_low <= 0) return;

    if (!ib.valid) {
        ib.high = price_high;
        ib.low  = price_low;
        ib.valid = true;
    } else {
        if (price_high > ib.high) ib.high = price_high;
        if (price_low  < ib.low)  ib.low  = price_low;
    }

    ib.mid         = (ib.high + ib.low) / 2.0f;
    ib.range_ticks = (ib.high - ib.low) / tick_size;

    float atr_ticks = atr / tick_size;
    if (atr_ticks > 0) {
        ib.is_narrow = ib.range_ticks < atr_ticks * ASIA_IB_NARROW_PCT;
        ib.is_wide   = ib.range_ticks > atr_ticks * ASIA_IB_WIDE_PCT;
    }
}

// ── Vérifier si l'IB a été cassée (appeler après l'IB) ──
inline void CheckIBBreak(IBRange& ib, float current_price) {
    if (!ib.valid) return;
    if (current_price > ib.high && !ib.broken_up) ib.broken_up = true;
    if (current_price < ib.low  && !ib.broken_dn) ib.broken_dn = true;
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — DIAGNOSTIC STRUCTUREL
// ═══════════════════════════════════════════════════════════════════════════════

// ── Détecter la forme du profil ──
// poc_ratio = position du POC dans le range (0.0=bas, 1.0=haut)
// has_double_dist = détecté par SC (volume bimodal)
inline ProfileShape DiagnoseProfileShape(float poc_ratio, bool has_double_dist) {
    if (has_double_dist)            return SHAPE_D;
    if (poc_ratio > POC_HIGH_THRESHOLD) return SHAPE_P;
    if (poc_ratio < POC_LOW_THRESHOLD)  return SHAPE_B;
    return SHAPE_SYM;
}

// ── Déterminer le régime ──
// open_type: 1=OD_UP, 2=OD_DN, 3=ORR_UP, 4=ORR_DN, 5-9=autres
// gap_ticks: positif=gap up, négatif=gap down
inline void DetermineRegime(SessionPlan& plan, int open_type, float gap_ticks) {
    float conf = 0.0f;
    ProfileShape shape = plan.prev_shape;

    // ── Règle 1: Double distribution → RANGE ──
    if (shape == SHAPE_D) {
        plan.regime = PLAN_RANGE;
        conf += 0.40f;
    }
    // ── Règle 2: Open Drive → TREND (haute conviction) ──
    else if (open_type == 1 || open_type == 8) {  // OD_UP, OTD_UP
        plan.regime = PLAN_TREND_UP;
        plan.bias   = +1;
        conf += 0.60f;
    }
    else if (open_type == 2 || open_type == 9) {  // OD_DN, OTD_DN
        plan.regime = PLAN_TREND_DN;
        plan.bias   = -1;
        conf += 0.60f;
    }
    // ── Règle 3: Profile B/P + gap ──
    else if (shape == SHAPE_B) {
        plan.bias = +1;
        if (gap_ticks > 40.0f) {
            plan.regime = PLAN_TREND_UP;
            conf += 0.35f;
        } else {
            plan.regime = PLAN_ROTATION;
            conf += 0.25f;
        }
    }
    else if (shape == SHAPE_P) {
        plan.bias = -1;
        if (gap_ticks < -40.0f) {
            plan.regime = PLAN_TREND_DN;
            conf += 0.35f;
        } else {
            plan.regime = PLAN_ROTATION;
            conf += 0.25f;
        }
    }
    // ── Règle 4: Symétrique ──
    else {
        plan.regime = PLAN_ROTATION;
        conf += 0.20f;
    }

    // ── Bonus Asia IB ──
    int asia_dir = plan.asia_ib.direction_bias();
    if (asia_dir != 0 && plan.bias != 0) {
        if (asia_dir == plan.bias) conf += 0.10f;
        else                       conf -= 0.10f;
    }

    // ── Bonus IB narrow/wide ──
    const IBRange& ib = plan.active_ib();
    if (ib.valid && ib.is_narrow) conf += 0.05f;
    if (ib.valid && ib.is_wide)   conf += 0.05f;

    plan.confidence = (conf < 0.0f) ? 0.0f : ((conf > 1.0f) ? 1.0f : conf);
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — CONFIGURATION MODULES & RISK
// ═══════════════════════════════════════════════════════════════════════════════

inline void ConfigureModules(SessionPlan& plan) {
    switch (plan.regime) {
        case PLAN_RANGE:
            plan.mod_rvol       = true;
            plan.mod_range      = true;   // Range Entry = cœur du range
            plan.mod_double_top = true;   // DT = signal le plus fort en range
            plan.mod_exhaustion = true;
            plan.mod_zone       = true;
            plan.sl_tight       = true;   // SL serré en range
            plan.trailing_on    = false;  // Trailing OFF en range strict
            plan.max_trades_session = 5;
            break;

        case PLAN_TREND_UP:
        case PLAN_TREND_DN:
            plan.mod_rvol       = true;
            plan.mod_range      = false;  // Range Entry = contre-tendance = DANGER
            plan.mod_double_top = true;   // Confirme les pullbacks
            plan.mod_exhaustion = true;   // Détecte les pullbacks épuisés
            plan.mod_zone       = true;
            plan.sl_tight       = false;  // SL large en trend
            plan.trailing_on    = true;   // Trailing ON = capturer le move
            plan.max_trades_session = 4;
            break;

        case PLAN_BREAKOUT:
            plan.mod_rvol       = true;
            plan.mod_range      = false;
            plan.mod_double_top = false;  // Pas de reversal en breakout
            plan.mod_exhaustion = true;
            plan.mod_zone       = true;
            plan.sl_tight       = false;
            plan.trailing_on    = true;
            plan.max_trades_session = 4;
            break;

        case PLAN_ROTATION:
        default:
            plan.mod_rvol       = true;
            plan.mod_range      = true;
            plan.mod_double_top = true;
            plan.mod_exhaustion = true;
            plan.mod_zone       = true;
            plan.sl_tight       = false;
            plan.trailing_on    = true;
            plan.max_trades_session = 5;
            break;
    }

    // Sizing
    if (plan.confidence >= HIGH_CONVICTION)
        plan.sizing_factor = 1.25f;
    else if (plan.confidence <= LOW_CONVICTION)
        plan.sizing_factor = 0.75f;
    else
        plan.sizing_factor = 1.0f;
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — IDENTIFICATION DES TARGETS
// ═══════════════════════════════════════════════════════════════════════════════

// Helper: ajouter un target à la liste
inline void AddTarget(PlanTarget* targets, int& count, int max_count,
                      const char* name, float dist_ticks, float price,
                      float conviction, int tier) {
    if (count >= max_count) return;
    if (dist_ticks < TARGET_MIN_DIST_TICKS) return;   // Déjà sur le target
    if (dist_ticks > TARGET_MAX_DIST_TICKS) return;   // Trop loin

    PlanTarget& t = targets[count];
    strncpy(t.name, name, 23);
    t.name[23]    = '\0';
    t.dist_ticks  = dist_ticks;
    t.price       = price;
    t.conviction  = conviction;
    t.tier        = tier;
    count++;
}

// ── Scanner les targets structurels ──
// Appeler avec les données de la dernière barre
inline void IdentifyTargets(SessionPlan& plan,
                            float price,
                            float tick_size,
                            // PREV levels
                            float prev_vpoc, float prev_vah, float prev_val,
                            float prev_vwap,
                            // Current session
                            float cur_vpoc, float cur_vah, float cur_val,
                            // MQ + GEX
                            float mq_hvl, float mq_put_0dte, float mq_call_0dte,
                            float gex_up, float gex_dn,
                            // OVN
                            float ovn_high, float ovn_low,
                            // Open
                            float open_cash,
                            // Session phase (pour activer 0DTE en US only)
                            SessionPhase phase) {

    plan.n_targets_up = 0;
    plan.n_targets_dn = 0;
    plan.has_primary  = false;

    // Helper lambda: dist en ticks, positif = au-dessus du prix
    auto dist = [&](float level) -> float {
        return (level - price) / tick_size;
    };

    // ── Structure: target_map (name, level, conviction, is_magnet) ──
    struct TargetCandidate {
        const char* name;
        float level;
        float conviction;
    };

    TargetCandidate candidates[20];
    int n_cands = 0;

    // PREV levels — toujours actifs
    if (prev_vpoc > 0) candidates[n_cands++] = {"PREV_VPOC", prev_vpoc, 0.80f};
    if (prev_vwap > 0) candidates[n_cands++] = {"PREV_VWAP", prev_vwap, 0.60f};
    if (prev_vah  > 0) candidates[n_cands++] = {"PREV_VAH",  prev_vah,  0.50f};
    if (prev_val  > 0) candidates[n_cands++] = {"PREV_VAL",  prev_val,  0.50f};

    // Current session
    if (cur_vpoc > 0)  candidates[n_cands++] = {"CUR_VPOC",  cur_vpoc,  0.70f};
    if (cur_vah  > 0)  candidates[n_cands++] = {"CUR_VAH",   cur_vah,   0.55f};
    if (cur_val  > 0)  candidates[n_cands++] = {"CUR_VAL",   cur_val,   0.55f};

    // MQ
    if (mq_hvl   > 0)  candidates[n_cands++] = {"MQ_HVL",    mq_hvl,    0.45f};

    // 0DTE — actif en US seulement
    if (phase >= PHASE_US_IB_FORMING) {
        if (mq_put_0dte  > 0)  candidates[n_cands++] = {"PUT_0DTE",  mq_put_0dte,  0.65f};
        if (mq_call_0dte > 0)  candidates[n_cands++] = {"CALL_0DTE", mq_call_0dte, 0.65f};
    }

    // GEX
    if (gex_up > 0) candidates[n_cands++] = {"GEX_UP", gex_up, 0.55f};
    if (gex_dn > 0) candidates[n_cands++] = {"GEX_DN", gex_dn, 0.55f};

    // OVN
    if (ovn_high > 0) candidates[n_cands++] = {"OVN_HIGH", ovn_high, 0.40f};
    if (ovn_low  > 0) candidates[n_cands++] = {"OVN_LOW",  ovn_low,  0.40f};

    // Open
    if (open_cash > 0) candidates[n_cands++] = {"OPEN_CASH", open_cash, 0.35f};

    // ── Classer UP vs DOWN ──
    for (int i = 0; i < n_cands; i++) {
        float d = dist(candidates[i].level);
        float abs_d = (d >= 0) ? d : -d;

        if (abs_d < TARGET_MIN_DIST_TICKS || abs_d > TARGET_MAX_DIST_TICKS)
            continue;

        // Bonus proximité
        float adj_conv = candidates[i].conviction;
        adj_conv += (100.0f - abs_d) / 200.0f;  // 0 à +0.5
        if (adj_conv > 1.0f) adj_conv = 1.0f;

        // Bonus régime
        if (plan.regime == PLAN_RANGE) adj_conv += 0.10f;

        int tier = (adj_conv >= 0.65f) ? 1 : ((adj_conv >= 0.45f) ? 2 : 3);

        if (d > 0) {
            AddTarget(plan.targets_up, plan.n_targets_up, 5,
                      candidates[i].name, abs_d, candidates[i].level,
                      adj_conv, tier);
        } else {
            AddTarget(plan.targets_dn, plan.n_targets_dn, 5,
                      candidates[i].name, abs_d, candidates[i].level,
                      adj_conv, tier);
        }
    }

    // Asia IB comme targets
    if (plan.asia_ib.valid) {
        float d_high = dist(plan.asia_ib.high);
        float d_low  = dist(plan.asia_ib.low);
        float abs_h = (d_high >= 0) ? d_high : -d_high;
        float abs_l = (d_low  >= 0) ? d_low  : -d_low;

        if (d_high > 0 && abs_h >= TARGET_MIN_DIST_TICKS)
            AddTarget(plan.targets_up, plan.n_targets_up, 5,
                      "ASIA_IB_HIGH", abs_h, plan.asia_ib.high, 0.50f, 2);
        if (d_low < 0 && abs_l >= TARGET_MIN_DIST_TICKS)
            AddTarget(plan.targets_dn, plan.n_targets_dn, 5,
                      "ASIA_IB_LOW", abs_l, plan.asia_ib.low, 0.50f, 2);
    }

    // ── Primary target = celui avec la plus haute conviction ──
    // dans la direction du biais
    if (plan.bias > 0 && plan.n_targets_up > 0) {
        plan.primary_target = plan.targets_up[0];  // Déjà trié par conviction
        plan.has_primary = true;
    } else if (plan.bias < 0 && plan.n_targets_dn > 0) {
        plan.primary_target = plan.targets_dn[0];
        plan.has_primary = true;
    } else {
        // Pas de biais → le target le plus convaincant donne le biais
        float best_up = (plan.n_targets_up > 0) ? plan.targets_up[0].conviction : 0;
        float best_dn = (plan.n_targets_dn > 0) ? plan.targets_dn[0].conviction : 0;
        if (best_up > best_dn && best_up > 0.3f) {
            plan.primary_target = plan.targets_up[0];
            plan.has_primary = true;
            if (plan.bias == 0) plan.bias = +1;
        } else if (best_dn > 0.3f) {
            plan.primary_target = plan.targets_dn[0];
            plan.has_primary = true;
            if (plan.bias == 0) plan.bias = -1;
        }
    }
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9 — INTRA-SESSION UPDATE
// ═══════════════════════════════════════════════════════════════════════════════

inline void UpdatePlan(SessionPlan& plan, float current_price,
                       bool inside_prev_va, float dist_prev_vpoc,
                       float tick_size) {

    // ── Vérifier cassures IB ──
    CheckIBBreak(plan.asia_ib,   current_price);
    CheckIBBreak(plan.london_ib, current_price);
    CheckIBBreak(plan.us_ib,     current_price);

    // ── IB US cassée → upgrade BREAKOUT ──
    if (plan.us_ib.valid) {
        if ((plan.us_ib.broken_up || plan.us_ib.broken_dn)
            && plan.regime != PLAN_BREAKOUT) {
            plan.regime = PLAN_BREAKOUT;
            plan.bias = plan.us_ib.direction_bias();
            plan.confidence += 0.15f;
            if (plan.confidence > 1.0f) plan.confidence = 1.0f;
            ConfigureModules(plan);  // Re-configurer
        }
    }

    // ── Rule of 80%: prix revient dans prev VA → VPOC target ──
    if (inside_prev_va && dist_prev_vpoc != 0.0f) {
        float abs_d = (dist_prev_vpoc >= 0) ? dist_prev_vpoc : -dist_prev_vpoc;
        if (abs_d > TARGET_MIN_DIST_TICKS) {
            float price_vpoc = current_price + dist_prev_vpoc * tick_size;
            plan.primary_target = {"PREV_VPOC_80%", price_vpoc,
                                   abs_d, 0.80f, 1};
            plan.has_primary = true;
            plan.bias = (dist_prev_vpoc > 0) ? +1 : -1;
        }
    }
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 10 — BUILD PLAN (point d'entrée principal)
// ═══════════════════════════════════════════════════════════════════════════════
//
// Appeler 1x au début de chaque session depuis MIA_Main.cpp:
//
//   SessionPhase phase = DetectPhase(time_et);
//   if (phase != last_phase) {
//       // Nouvelle session → recalculer le plan
//       plan = BuildSessionPlan(sc, d, config, phase);
//       last_phase = phase;
//   }
//   // À chaque barre:
//   UpdatePlan(plan, d.price_close, inside_prev_va, dist_prev_vpoc, config.tick_size);
//
// Le plan est ensuite consulté par MIA_Entry.h pour décider si on trade.

inline SessionPlan BuildSessionPlan(
    SCStudyInterfaceRef sc,
    float price,
    float tick_size,
    float atr,
    // Profile
    float poc_ratio,         // 0.0-1.0, position du POC dans le range
    bool  has_double_dist,   // SC Volume Profile bimodal flag
    int   open_type,         // 1-9
    float gap_ticks,         // Open gap en ticks
    // Levels
    float prev_vpoc, float prev_vah, float prev_val, float prev_vwap,
    float cur_vpoc, float cur_vah, float cur_val,
    float mq_hvl, float mq_put_0dte, float mq_call_0dte,
    float gex_up, float gex_dn,
    float ovn_high, float ovn_low, float open_cash,
    // IB (déjà calculées par l'appelant)
    const IBRange& asia_ib,
    SessionPhase phase)
{
    SessionPlan plan;
    plan.current_phase = phase;

    // ── 1. Copier les IB ──
    plan.asia_ib = asia_ib;
    // london_ib et us_ib seront remplies par l'appelant au fil des sessions

    // ── 2. Diagnostic structurel ──
    plan.prev_shape = DiagnoseProfileShape(poc_ratio, has_double_dist);

    // ── 3. Déterminer régime et biais ──
    DetermineRegime(plan, open_type, gap_ticks);

    // ── 4. Configurer modules et risk ──
    ConfigureModules(plan);

    // ── 5. Identifier targets ──
    IdentifyTargets(plan, price, tick_size,
                    prev_vpoc, prev_vah, prev_val, prev_vwap,
                    cur_vpoc, cur_vah, cur_val,
                    mq_hvl, mq_put_0dte, mq_call_0dte,
                    gex_up, gex_dn, ovn_high, ovn_low, open_cash,
                    phase);

    plan.plan_valid = true;

    // ── Log ──
    plan.log(sc);

    return plan;
}
