#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_OpenType.h  —  MIA Data Dumper G3 : Section D — CLASSIFICATION CONTEXTE
// Version 2.0 — Guide Professionnel (Steidlmayer / Dalton / Pratiques OTF)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rôle : Classifier automatiquement le contexte d'ouverture de session.
//         Écrit 5 champs dans DMP_MLFeatures :
//
//    f.open_type      → Type d'ouverture (12 valeurs, direction incluse)
//    f.open_zone      → Zone d'ouverture vs PDH/PDL/VAH/VAL/POC (7 zones)
//    f.open_bias_conf → Confiance directionnelle (0.0-1.0)
//    f.day_type       → Type de journée (5 valeurs, mis à jour progressivement)
//    f.rule_80pct     → Règle des 80% — machine à états, booléen 0/1
//
//  ── ENUM open_type (12 valeurs) ──────────────────────────────────────────────
//
//     0 = UNKNOWN       Avant 10h30, pas encore classifiable
//     1 = OD_UP         Open Drive Up    — Trend Day haussier probable (85%)
//     2 = OD_DOWN       Open Drive Down  — Trend Day baissier probable (85%)
//     3 = OTD_UP        Open Test Drive Up   — 70%
//     4 = OTD_DOWN      Open Test Drive Down — 70%
//     5 = ORR_UP        Open Rejection Reverse Up  — 60%
//     6 = ORR_DOWN      Open Rejection Reverse Down — 60%
//     7 = OAIR          Open Auction In Range — 30% (journée range)
//     8 = OAOR_UP       Open Auction Out Range Up  — 65% (gap non comblé)
//     9 = OAOR_DOWN     Open Auction Out Range Down — 65%
//    10 = ODF_UP        Open Drive FAIL Up   — 90% reversal violent (DANGER)
//    11 = ODF_DOWN      Open Drive FAIL Down — 90% reversal violent (DANGER)
//
//  ── ENUM open_zone (7 zones) ─────────────────────────────────────────────────
//
//    7 > PDH              Gap up majeur    — OTF massifs, Trend Day probable
//    6 PDH→VAH            Gap up modéré    — OTD/OD possible, haussier
//    5 VAH→POC            Dans VA haute    — légèrement bullish
//    4 ≈POC (±3 ticks)    Équilibre exact  — neutre, rotation
//    3 POC→VAL            Dans VA basse    — légèrement bearish
//    2 VAL→PDL            Gap down modéré  — OTD/OD possible, baissier
//    1 < PDL              Gap down majeur  — OTF massifs, Trend Day probable
//
//  ── ENUM day_type (5 valeurs) ────────────────────────────────────────────────
//
//    0 = NonTrend   IB < 15% ATR   ( 7% — marché comprimé, news imminentes)
//    1 = Normal     IB > 80% ATR   ( 2% — range sans extension)
//    2 = NormVar    Ext. 1 côté    (42% — le plus fréquent, défaut)
//    3 = Neutral    Ext. 2 côtés + close milieu (30% — whipsaw)
//    4 = Trend      Ext. > 2×IB sur 1 côté (19% — éviter contre-tendance)
//
//  ── RÈGLE DES 80% ────────────────────────────────────────────────────────────
//
//    Conditions : Open HORS VA → rentre dans VA → y reste 2×30min (60 barres)
//    Résultat   : 80% de probabilité de traverser TOUTE la VA (VAH→VAL ou inverse)
//
//  ── PERSISTANCE sc.GetPersistentFloat (indices 80-89) ────────────────────────
//
//    80 = open_type_cached    (DMP_OT_NOT_SET = -1 si pas encore calculé)
//    81 = day_type_cached     (2.0 = NormVar par défaut)
//    82 = price_at_1030       (DMP_OT_NOT_SET si pas encore capturé)
//    83 = rule_80pct_state    (0=IDLE / 1=PRIMED / 2=IN_VA / 3=CONFIRMED)
//    84 = rule_80pct_bar      (sc.Index à l'entrée en VA)
//    85 = open_zone_cached    (DMP_OT_NOT_SET si pas encore calculé)
//    86 = pdh_cached          (Previous Day High — inter-sessions, NE PAS RESET)
//    87 = pdl_cached          (Previous Day Low  — inter-sessions, NE PAS RESET)
//    88 = (réservé)
//    89 = (réservé)
//
//  ⚠️  Indices 50-74 réservés par DMP_HVN_LVN.h — aucun conflit.
//
//  Dépendances : DMP_Transform.h (inclut DMP_Reader.h + DMP_HVN_LVN.h)
//  Appelé depuis DMP_Main.cpp APRÈS DMP_Transform().
//
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_Transform.h"

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// ── Indices persistants ───────────────────────────────────────────────────────
constexpr int DMP_OT_P_OPEN_TYPE  = 80;
constexpr int DMP_OT_P_DAY_TYPE   = 81;
constexpr int DMP_OT_P_PRICE_1030 = 82;
constexpr int DMP_OT_P_R80_STATE  = 83;
constexpr int DMP_OT_P_R80_BAR    = 84;
constexpr int DMP_OT_P_OPEN_ZONE  = 85;
constexpr int DMP_OT_P_PDH        = 86;
constexpr int DMP_OT_P_PDL        = 87;

// ── Sentinelle ────────────────────────────────────────────────────────────────
constexpr float DMP_OT_NOT_SET = -1.0f;

// ── Valeurs open_type ─────────────────────────────────────────────────────────
constexpr float OT_UNKNOWN    =  0.0f;
constexpr float OT_OD_UP      =  1.0f;
constexpr float OT_OD_DOWN    =  2.0f;
constexpr float OT_OTD_UP     =  3.0f;
constexpr float OT_OTD_DOWN   =  4.0f;
constexpr float OT_ORR_UP     =  5.0f;
constexpr float OT_ORR_DOWN   =  6.0f;
constexpr float OT_OAIR       =  7.0f;
constexpr float OT_OAOR_UP    =  8.0f;
constexpr float OT_OAOR_DOWN  =  9.0f;
constexpr float OT_ODF_UP     = 10.0f;
constexpr float OT_ODF_DOWN   = 11.0f;

// ── Valeurs open_zone ─────────────────────────────────────────────────────────
constexpr float OZ_BELOW_PDL   = 1.0f;
constexpr float OZ_VAL_PDL     = 2.0f;
constexpr float OZ_POC_VAL     = 3.0f;
constexpr float OZ_AT_POC      = 4.0f;
constexpr float OZ_VAH_POC     = 5.0f;
constexpr float OZ_PDH_VAH     = 6.0f;
constexpr float OZ_ABOVE_PDH   = 7.0f;

// ── États rule_80pct ──────────────────────────────────────────────────────────
constexpr float R80_IDLE      = 0.0f;
constexpr float R80_PRIMED    = 1.0f;
constexpr float R80_IN_VA     = 2.0f;
constexpr float R80_CONFIRMED = 3.0f;

// ── Seuils de classification ──────────────────────────────────────────────────
constexpr float DMP_OT_POC_TOL_TICKS  = 3.0f;  // ±3 ticks = "at POC"
constexpr float DMP_OT_OD_RATIO       = 0.75f; // > 75% IB = Open Drive
constexpr float DMP_OT_OAIR_RATIO     = 0.50f; // ≤ 50% IB = OAIR (range)
constexpr float DMP_OT_ODF_TICKS      = 8.0f;  // Reversal > 8 ticks = ODF
// DMP_OT_GetR80Bars(sc) calcule dynamiquement selon le timeframe du chart
// Fallback si sc.SecondsPerBar indisponible (assume chart 1-min)
constexpr int   DMP_OT_R80_BARS_FALLBACK = 60; // 60 barres × 1min = 60min = 2×30min
constexpr float DMP_DT_NONTREND       = 0.15f; // IB < 15% ATR → NonTrend
constexpr float DMP_DT_NORMAL         = 0.80f; // IB > 80% ATR → Normal
constexpr float DMP_DT_TREND_MULT     = 2.0f;  // Ext > 2×IB → Trend
constexpr float DMP_DT_NEUTRAL_CENTER = 0.35f; // Close dans ±35% milieu

// ── Confiances (guide pro — Section 7) ───────────────────────────────────────
constexpr float DMP_OT_CONF_ODF  = 0.90f; // Signal sortie urgente
constexpr float DMP_OT_CONF_OD   = 0.85f; // Ne jamais fader
constexpr float DMP_OT_CONF_OTD  = 0.70f;
constexpr float DMP_OT_CONF_OAOR = 0.65f;
constexpr float DMP_OT_CONF_ORR  = 0.60f;
constexpr float DMP_OT_CONF_OAIR = 0.30f;
constexpr float DMP_OT_CONF_UNKN = 0.00f;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — PDH / PDL (Previous Day High/Low)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Stratégie : mémoriser le High/Low de session en fin de journée RTH (15h30+).
//  Ces valeurs sont inter-sessions → jamais réinitialisées par DMP_OT_ResetSession.

static inline void DMP_OT_SaveEODLevels(SCStudyInterfaceRef sc,
                                         float sess_high, float sess_low)
{
    if (DMP_IsPriceValid(sess_high)) sc.GetPersistentFloat(DMP_OT_P_PDH) = sess_high;
    if (DMP_IsPriceValid(sess_low))  sc.GetPersistentFloat(DMP_OT_P_PDL) = sess_low;
}

static inline float DMP_OT_PDH(SCStudyInterfaceRef sc) {
    return sc.GetPersistentFloat(DMP_OT_P_PDH);
}
static inline float DMP_OT_PDL(SCStudyInterfaceRef sc) {
    return sc.GetPersistentFloat(DMP_OT_P_PDL);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — RESET DE SESSION
// ═══════════════════════════════════════════════════════════════════════════════

static inline bool DMP_OT_IsNewSession(SCStudyInterfaceRef sc) {
    return (sc.Index > 0 && sc.IsNewTradingDay(sc.Index));
}

static inline void DMP_OT_ResetSession(SCStudyInterfaceRef sc) {
    sc.GetPersistentFloat(DMP_OT_P_OPEN_TYPE)  = DMP_OT_NOT_SET;
    sc.GetPersistentFloat(DMP_OT_P_DAY_TYPE)   = 2.0f;  // NormVar
    sc.GetPersistentFloat(DMP_OT_P_PRICE_1030) = DMP_OT_NOT_SET;
    sc.GetPersistentFloat(DMP_OT_P_R80_STATE)  = R80_IDLE;
    sc.GetPersistentFloat(DMP_OT_P_R80_BAR)    = DMP_OT_NOT_SET;
    sc.GetPersistentFloat(DMP_OT_P_OPEN_ZONE)  = DMP_OT_NOT_SET;
    // PDH (86) et PDL (87) : NE PAS RÉINITIALISER — inter-sessions
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — OPEN ZONE (7 zones vs PDH/PDL/VAH/VAL/POC)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Calculé UNE SEULE FOIS dès que open_cash est disponible (9h30 ET).
//  Si PDH/PDL non disponibles (1er jour), utilise VAH/VAL comme fallback.

static inline float DMP_ClassifyOpenZone(
    float open_cash,
    float prev_vah, float prev_val, float prev_vpoc,
    float pdh, float pdl, float tick_size)
{
    if (!DMP_IsPriceValid(open_cash)) return OZ_AT_POC;
    const float tol = DMP_OT_POC_TOL_TICKS * tick_size;

    // Zone 7 : au-dessus de PDH
    if (DMP_IsPriceValid(pdh) && open_cash > pdh)
        return OZ_ABOVE_PDH;

    // Zone 6 : entre PDH et VAH (gap up modéré)
    if (DMP_IsPriceValid(prev_vah) && open_cash > prev_vah)
        return OZ_PDH_VAH;

    // Zone 5 : entre VAH et POC (dans VA haute)
    if (DMP_IsPriceValid(prev_vpoc) && open_cash > prev_vpoc + tol)
        return OZ_VAH_POC;

    // Zone 4 : autour du POC (équilibre)
    if (DMP_IsPriceValid(prev_vpoc) && std::fabs(open_cash - prev_vpoc) <= tol)
        return OZ_AT_POC;

    // Zone 3 : entre POC et VAL (dans VA basse)
    if (DMP_IsPriceValid(prev_val) && open_cash > prev_val)
        return OZ_POC_VAL;

    // Zone 2 : entre VAL et PDL (gap down modéré)
    if (DMP_IsPriceValid(pdl) && open_cash > pdl)
        return OZ_VAL_PDL;

    // Zone 1 : en dessous de PDL
    return OZ_BELOW_PDL;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — OPEN TYPE (12 valeurs, direction incluse)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Appelé UNE SEULE FOIS à 10h30 ET.
//  Compare open_cash (9h30) vs price_at_1030 pour identifier le comportement OTF.
//
//  Priorité de détection (confiance décroissante) :
//    1. OD  : mouvement > 75% IB → signal le plus fort
//    2. ORR : ouvre hors VA + reversal dans VA
//    3. OAOR: ouvre hors VA + reste hors VA (gap qui tient)
//    4. OTD : ouvre dans VA + mouvement > 50% IB
//    5. OAIR: ouvre dans VA + mouvement faible (journée range)

static inline float DMP_ClassifyOpenType(
    float open_cash,
    float prev_vah, float prev_val,
    float ib_high, float ib_low,
    float price_at_1030)
{
    if (!DMP_IsPriceValid(open_cash)     || !DMP_IsPriceValid(prev_vah) ||
        !DMP_IsPriceValid(prev_val)      || !DMP_IsPriceValid(ib_high)  ||
        !DMP_IsPriceValid(ib_low)        || !DMP_IsPriceValid(price_at_1030))
        return OT_UNKNOWN;

    const float ib_range = ib_high - ib_low;
    if (ib_range <= 0.0f) return OT_UNKNOWN;

    const bool open_above_va = (open_cash > prev_vah);
    const bool open_below_va = (open_cash < prev_val);
    const bool open_in_va    = !open_above_va && !open_below_va;
    const float move     = price_at_1030 - open_cash;
    const float move_abs = std::fabs(move);
    const bool  move_up  = (move > 0.0f);

    // ── 1. OPEN DRIVE (85%) : mouvement fort et direct (> 75% IB) ─────────────
    if (move_abs > ib_range * DMP_OT_OD_RATIO)
        return move_up ? OT_OD_UP : OT_OD_DOWN;

    // ── 2. ORR (60%) : ouverture hors VA + reversal rentré dans VA ────────────
    if (open_above_va && price_at_1030 < prev_vah) return OT_ORR_DOWN;
    if (open_below_va && price_at_1030 > prev_val) return OT_ORR_UP;

    // ── 3. OAOR (65%) : gap hors VA qui tient, prix reste hors VA ────────────
    if (open_above_va && price_at_1030 > prev_vah) return OT_OAOR_UP;
    if (open_below_va && price_at_1030 < prev_val) return OT_OAOR_DOWN;

    // ── 4. OTD (70%) : dans VA + mouvement directionnel > 50% IB ─────────────
    if (open_in_va && move_abs > ib_range * DMP_OT_OAIR_RATIO)
        return move_up ? OT_OTD_UP : OT_OTD_DOWN;

    // ── 5. OAIR (30%) : dans VA + mouvement faible → journée range ────────────
    return OT_OAIR;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
static inline float DMP_OT_Confidence(float ot) {
    const int v = (int)ot;
    if (v == 10 || v == 11) return DMP_OT_CONF_ODF;
    if (v ==  1 || v ==  2) return DMP_OT_CONF_OD;
    if (v ==  3 || v ==  4) return DMP_OT_CONF_OTD;
    if (v ==  8 || v ==  9) return DMP_OT_CONF_OAOR;
    if (v ==  5 || v ==  6) return DMP_OT_CONF_ORR;
    if (v ==  7)            return DMP_OT_CONF_OAIR;
    return DMP_OT_CONF_UNKN;
}

static inline const char* DMP_OT_Name(float ot) {
    switch ((int)ot) {
        case  1: return "OD_UP";    case  2: return "OD_DOWN";
        case  3: return "OTD_UP";   case  4: return "OTD_DOWN";
        case  5: return "ORR_UP";   case  6: return "ORR_DOWN";
        case  7: return "OAIR";
        case  8: return "OAOR_UP";  case  9: return "OAOR_DOWN";
        case 10: return "ODF_UP";   case 11: return "ODF_DOWN";
        default: return "UNKNOWN";
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — OPEN DRIVE FAIL (ODF) — Surveillance continue
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Surveille chaque barre si un OD est actif.
//  OD_UP → cassure du Low IB de > 8 ticks = ODF_UP (reversal violent)
//  OD_DOWN → cassure du High IB de > 8 ticks = ODF_DOWN
//
//  Règle pro : "Si position dans le sens du Drive → sortir IMMÉDIATEMENT"

static inline float DMP_CheckODF(
    float open_type, float price_close,
    float ib_high, float ib_low, float tick_size)
{
    if (open_type != OT_OD_UP && open_type != OT_OD_DOWN)
        return open_type;
    if (!DMP_IsPriceValid(price_close)) return open_type;

    const float threshold = DMP_OT_ODF_TICKS * tick_size;

    if (open_type == OT_OD_UP && DMP_IsPriceValid(ib_low)) {
        if (price_close < ib_low - threshold) return OT_ODF_UP;
    }
    if (open_type == OT_OD_DOWN && DMP_IsPriceValid(ib_high)) {
        if (price_close > ib_high + threshold) return OT_ODF_DOWN;
    }
    return open_type;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — DAY TYPE (5 valeurs)
// ═══════════════════════════════════════════════════════════════════════════════

static inline float DMP_CalcIBRangeATR(float ib_high, float ib_low, float atr_ticks, float tick_size) {
    // FIX 2026-04-15 : atr_ticks est en TICKS, ib_high/ib_low en POINTS.
    // Avant fix : (ib_high - ib_low) / atr retournait pts/ticks = ratio 4x trop petit.
    // Apres fix : conversion ib_range en ticks via tick_size, puis division homogene.
    if (!DMP_IsPriceValid(ib_high) || !DMP_IsPriceValid(ib_low))       return DMP_INVALID;
    if (!DMP_IsValid(atr_ticks) || atr_ticks <= 0.0f)                  return DMP_INVALID;
    if (!DMP_IsValid(tick_size) || tick_size <= 0.0f)                  return DMP_INVALID;
    if (ib_high <= ib_low)                                              return DMP_INVALID;
    const float ib_range_ticks = (ib_high - ib_low) / tick_size;
    return ib_range_ticks / atr_ticks;
}

static inline int DMP_ClassifyDayType(
    float ib_atr, float sess_high, float sess_low,
    float price_close, float ib_high, float ib_low)
{
    if (!DMP_IsValid(ib_atr) || ib_atr <= 0.0f)                  return 2;
    if (!DMP_IsPriceValid(sess_high) || !DMP_IsPriceValid(sess_low)) return 2;
    if (!DMP_IsPriceValid(ib_high)  || !DMP_IsPriceValid(ib_low))   return 2;
    if (ib_high <= ib_low)                                            return 2;

    const float ib_range   = ib_high - ib_low;
    const bool  ext_up     = (sess_high > ib_high);
    const bool  ext_down   = (sess_low  < ib_low);
    const float ext_up_sz  = ext_up   ? (sess_high - ib_high) : 0.0f;
    const float ext_dn_sz  = ext_down ? (ib_low - sess_low)   : 0.0f;

    // 0 = NonTrend : IB ultra-comprimée (marché figé, news imminentes)
    if (ib_atr < DMP_DT_NONTREND) return 0;

    // 4 = Trend : extension forte sur 1 côté > 2×IB
    const bool strong_up = (ext_up_sz  > ib_range * DMP_DT_TREND_MULT);
    const bool strong_dn = (ext_dn_sz  > ib_range * DMP_DT_TREND_MULT);
    if ((strong_up && !ext_down) || (strong_dn && !ext_up)) return 4;

    // 3 = Neutral : extension des 2 côtés + close au milieu
    if (ext_up && ext_down && DMP_IsPriceValid(price_close)) {
        const float rng = sess_high - sess_low;
        if (rng > 0.0f) {
            const float pos = (price_close - sess_low) / rng;
            if (pos >= (0.5f - DMP_DT_NEUTRAL_CENTER) &&
                pos <= (0.5f + DMP_DT_NEUTRAL_CENTER)) return 3;
        }
    }

    // 1 = Normal : IB large, session contenue (ext < 20% IB)
    if (ib_atr >= DMP_DT_NORMAL) {
        if ((std::max)(ext_up_sz, ext_dn_sz) < ib_range * 0.20f) return 1;
    }

    // 2 = NormVar : défaut (42% des jours)
    return 2;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — RÈGLE DES 80%
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Machine à états 4 niveaux :
//    IDLE → PRIMED (prix sort de VA) → IN_VA (prix entre en VA) → CONFIRMED
//  Une fois CONFIRMED : reste 1.0 pour toute la session.

static inline float DMP_CheckRule80pct(
    SCStudyInterfaceRef sc,
    float price_close, float prev_vah, float prev_val)
{
    if (!DMP_IsPriceValid(price_close) ||
        !DMP_IsPriceValid(prev_vah)    ||
        !DMP_IsPriceValid(prev_val)    ||
        prev_vah <= prev_val) return 0.0f;

    float& state = sc.GetPersistentFloat(DMP_OT_P_R80_STATE);
    float& bar   = sc.GetPersistentFloat(DMP_OT_P_R80_BAR);

    const bool in_va = (price_close >= prev_val && price_close <= prev_vah);

    if (state == R80_CONFIRMED) return 1.0f;

    if (state == R80_IDLE) {
        if (!in_va) state = R80_PRIMED;
        return 0.0f;
    }

    if (state == R80_PRIMED) {
        if (in_va) { state = R80_IN_VA; bar = (float)sc.Index; }
        return 0.0f;
    }

    if (state == R80_IN_VA) {
        if (!in_va) { state = R80_PRIMED; bar = DMP_OT_NOT_SET; return 0.0f; }
        // R80 bars = 60 minutes / durée_barre_en_secondes
        // → Adaptatif au timeframe : 60 barres 1-min, 12 barres 5-min, 4 barres 15-min
        const int sec_per_bar = (sc.SecondsPerBar > 0) ? sc.SecondsPerBar : 60;
        const int r80_bars    = 3600 / sec_per_bar;  // 60 min cible
        if (sc.Index - (int)bar >= r80_bars) {
            state = R80_CONFIRMED;
            return 1.0f;
        }
        return 0.0f;
    }

    return 0.0f;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9 — CAPTURE PRIX À 10H30
// ═══════════════════════════════════════════════════════════════════════════════

static inline float DMP_OT_CapturePrice1030(
    SCStudyInterfaceRef sc, float price_close, bool ib_complete)
{
    float& cached = sc.GetPersistentFloat(DMP_OT_P_PRICE_1030);
    // 🆕 BUG #15 FIX (10/03/2026): SC reset PersistentFloat à 0.0 pas -1.0
    //   Après recompilation, cached=0.0 != NOT_SET(-1.0) → retourne 0.0
    //   → DMP_IsPriceValid(0.0)=false → classification BLOQUÉE à UNKNOWN
    if (cached != DMP_OT_NOT_SET && DMP_IsPriceValid(cached)) return cached;
    if (!ib_complete || !DMP_IsPriceValid(price_close)) return DMP_OT_NOT_SET;
    cached = price_close;
    return cached;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 10 — FONCTION MAÎTRE : DMP_UpdateOpenType()
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Point d'entrée unique — appelé depuis DMP_Main.cpp après DMP_Transform().
//
//  Ordre d'exécution :
//    1. Sauvegarde PDH/PDL en fin de session (15h30-16h00)
//    2. Reset si nouvelle session (PDH/PDL préservés)
//    3. open_zone (une fois, dès que open_cash disponible)
//    4. price_at_1030 + open_type (une fois, à 10h30)
//    5. ODF surveillance (chaque barre si OD actif)
//    6. day_type (3 fenêtres : 10h30 / 14h00 / 15h30)
//    7. rule_80pct (chaque barre)
//    8. Écriture dans f

// Forward declarations (définies Section 11a plus bas)
static inline float DMP_OT_Direction(float open_type);

inline void DMP_UpdateOpenType(
    SCStudyInterfaceRef sc,
    const DMP_RawData&  r,
    DMP_MLFeatures&     f)
{
    // Extraire l'heure ET depuis le timestamp Unix — même méthode que DMP_Reader.h
    // On ne fait PAS confiance à GetTimeHMS (dépend du timezone du chart).
    // L'ancien dumper (ligne 2701-2703) convertissait manuellement UTC → ET.
    SCDateTime bar_dt = sc.BaseDateTimeIn[sc.Index];
    long long ot_ts_ms = (long long)((bar_dt.GetAsDouble() - 25569.0) * 86400.0) * 1000LL;
    int h_et = 0, m_et = 0;
    {
        time_t ot_sec = (time_t)(ot_ts_ms / 1000);
        struct tm ot_gm{};
#ifdef _WIN32
        gmtime_s(&ot_gm, &ot_sec);
#else
        gmtime_r(&ot_sec, &ot_gm);
#endif
        // ⚠️ FIX DST 25/03/2026 — détection exacte via tm_wday
        //  Même logique que DMP_Reader.h et DMP_Writer.h.
        bool is_dst = false;
        {
            int mo = ot_gm.tm_mon + 1;
            int dy = ot_gm.tm_mday;
            int wday = ot_gm.tm_wday;  // 0=Sun, 1=Mon, ..., 6=Sat
            if (mo >= 4 && mo <= 10)                    is_dst = true;
            else if (mo == 3 && (dy - wday) >= 8)       is_dst = true;
            else if (mo == 11 && (dy - wday) < 1)       is_dst = true;
        }
        int utc_offset = is_dst ? 4 : 5;
        h_et = (ot_gm.tm_hour - utc_offset + 24) % 24;
        m_et = ot_gm.tm_min;
    }
    const int time_et = h_et * 60 + m_et;

    // ── 1. Sauvegarder PDH/PDL en fin de session ──────────────────────────────
    if (time_et >= 15 * 60 + 30 && r.is_rth_session)
        DMP_OT_SaveEODLevels(sc, r.sess_high, r.sess_low);

    // ── 2. Reset si nouvelle session ──────────────────────────────────────────
    if (DMP_OT_IsNewSession(sc))
        DMP_OT_ResetSession(sc);

    // Références persistants
    float& cached_ot   = sc.GetPersistentFloat(DMP_OT_P_OPEN_TYPE);
    float& cached_dt   = sc.GetPersistentFloat(DMP_OT_P_DAY_TYPE);
    float& cached_oz   = sc.GetPersistentFloat(DMP_OT_P_OPEN_ZONE);

    // PDH/PDL (peuvent être DMP_OT_NOT_SET le 1er jour)
    const float pdh = DMP_OT_PDH(sc);
    const float pdl = DMP_OT_PDL(sc);

    // ── 3. Open zone (une seule fois dès que open_cash valide) ───────────────
    // 🆕 BUG #15 FIX: SC reset cached_oz à 0.0 (pas -1.0) → zone invalide
    //   Zones valides = 1-7. Si 0.0 après reset, forcer recalcul.
    if ((cached_oz == DMP_OT_NOT_SET || cached_oz < 1.0f || cached_oz > 7.0f)
        && DMP_IsPriceValid(r.open_cash)) {
        // Fallback si PDH/PDL pas encore disponibles
        const float pdh_use = DMP_IsPriceValid(pdh) ? pdh : r.prev_vah;
        const float pdl_use = DMP_IsPriceValid(pdl) ? pdl : r.prev_val;

        cached_oz = DMP_ClassifyOpenZone(
            r.open_cash, r.prev_vah, r.prev_val, r.prev_vpoc,
            pdh_use, pdl_use, r.tick_size);

        char msg[160];
        snprintf(msg, sizeof(msg),
            "[DMP_OpenType] open_zone=%.0f | open=%.2f "
            "pdh=%.2f pvah=%.2f pvpoc=%.2f pval=%.2f pdl=%.2f",
            cached_oz, r.open_cash,
            DMP_IsPriceValid(pdh) ? pdh : 0.0f,
            r.prev_vah, r.prev_vpoc, r.prev_val,
            DMP_IsPriceValid(pdl) ? pdl : 0.0f);
        sc.AddMessageToLog(msg, 0);
    }

    // ── 4. Open type (une seule fois à 10h30) ─────────────────────────────────
    // 🆕 BUG #14 FIX: si cached_ot = OT_UNKNOWN (0) après un recalculate/erreur,
    //   le traiter comme NOT_SET pour permettre re-classification
    if (cached_ot == OT_UNKNOWN && r.ib_complete) {
        cached_ot = DMP_OT_NOT_SET;  // Forcer re-classification
    }

    if (cached_ot == DMP_OT_NOT_SET) {
        if (!r.ib_complete) {
            // Avant 10h30 : UNKNOWN
            f.open_type      = OT_UNKNOWN;
            f.open_bias_conf = DMP_OT_CONF_UNKN;
        } else {
            float p1030 = DMP_OT_CapturePrice1030(sc, r.price_close, true);
            if (p1030 != DMP_OT_NOT_SET &&
                DMP_IsPriceValid(r.open_cash) &&
                DMP_IsPriceValid(r.prev_vah)  &&
                DMP_IsPriceValid(r.prev_val)  &&
                DMP_IsPriceValid(r.ib_high)   &&
                DMP_IsPriceValid(r.ib_low))
            {
                float ot = DMP_ClassifyOpenType(
                    r.open_cash, r.prev_vah, r.prev_val,
                    r.ib_high, r.ib_low, p1030);
                
                // 🆕 Ne PAS verrouiller si résultat = UNKNOWN
                //   Sinon cached_ot=0 != NOT_SET=-1 → bloqué forever
                if (ot != OT_UNKNOWN) {
                    cached_ot = ot;
                }

                char msg[200];
                snprintf(msg, sizeof(msg),
                    "[DMP_OpenType] open_type=%s(%.0f) conf=%.2f | "
                    "open=%.2f pvah=%.2f pval=%.2f ib=[%.2f-%.2f] p1030=%.2f",
                    DMP_OT_Name(ot), ot, DMP_OT_Confidence(ot),
                    r.open_cash, r.prev_vah, r.prev_val,
                    r.ib_low, r.ib_high, p1030);
                sc.AddMessageToLog(msg, 0);
            } else {
                // 🆕 BUG #14 DIAGNOSTIC — pourquoi classification échoue ?
                char dbg[256];
                snprintf(dbg, sizeof(dbg),
                    "[DMP_OpenType] ⚠️ BLOCKED @ %02d:%02d | p1030=%.2f(%s) "
                    "open=%.2f(%s) pvah=%.2f(%s) pval=%.2f(%s) "
                    "ibH=%.2f(%s) ibL=%.2f(%s)",
                    h_et, m_et,
                    p1030, (p1030 != DMP_OT_NOT_SET ? "OK" : "NOT_SET"),
                    r.open_cash, (DMP_IsPriceValid(r.open_cash) ? "OK" : "FAIL"),
                    r.prev_vah,  (DMP_IsPriceValid(r.prev_vah)  ? "OK" : "FAIL"),
                    r.prev_val,  (DMP_IsPriceValid(r.prev_val)  ? "OK" : "FAIL"),
                    r.ib_high,   (DMP_IsPriceValid(r.ib_high)   ? "OK" : "FAIL"),
                    r.ib_low,    (DMP_IsPriceValid(r.ib_low)    ? "OK" : "FAIL"));
                sc.AddMessageToLog(dbg, 1);
            }
        }
    }

    // ── 5. ODF surveillance (chaque barre si OD actif) ────────────────────────
    if (cached_ot == OT_OD_UP || cached_ot == OT_OD_DOWN) {
        float new_ot = DMP_CheckODF(
            cached_ot, r.price_close, r.ib_high, r.ib_low, r.tick_size);
        if (new_ot != cached_ot) {
            char msg[128];
            snprintf(msg, sizeof(msg),
                "[DMP_OpenType] ⚠️ ODF: %s→%s | prix=%.2f ib=[%.2f-%.2f]",
                DMP_OT_Name(cached_ot), DMP_OT_Name(new_ot),
                r.price_close, r.ib_low, r.ib_high);
            sc.AddMessageToLog(msg, 1);
            cached_ot = new_ot;
        }
    }

    // ── 6. Day type (3 fenêtres de mise à jour) ───────────────────────────────
    if (r.ib_complete && r.is_rth_session) {
        const bool at_1400 = (time_et >= 14 * 60);
        const bool at_1530 = (time_et >= 15 * 60 + 30);
        // Mettre à jour si IB formée (10h30), 14h00, ou 15h30
        // En pratique : chaque barre après 10h30 (day_type affiné en continu)
        // Mais on log seulement sur changement
        float ib_atr = DMP_CalcIBRangeATR(r.ib_high, r.ib_low, r.atr_daily, r.tick_size);
        int dt = DMP_ClassifyDayType(ib_atr, r.sess_high, r.sess_low,
                                      r.price_close, r.ib_high, r.ib_low);
        if ((float)dt != cached_dt) {
            static const char* dt_names[] = {
                "NonTrend","Normal","NormVar","Neutral","Trend"
            };
            char msg[160];
            snprintf(msg, sizeof(msg),
                "[DMP_OpenType] day_type %s→%s @ %02d:%02d ET "
                "| ib_atr=%.2f sess=[%.2f-%.2f]",
                dt_names[(int)cached_dt], dt_names[dt],
                h_et, m_et,
                DMP_IsValid(ib_atr) ? ib_atr : 0.0f,
                r.sess_low, r.sess_high);
            sc.AddMessageToLog(msg, 0);
            cached_dt = (float)dt;
        }
    }

    // ── 7. Rule 80% (chaque barre en RTH) ─────────────────────────────────────
    f.rule_80pct = r.is_rth_session
        ? DMP_CheckRule80pct(sc, r.price_close, r.prev_vah, r.prev_val)
        : 0.0f;

    // ── 8. Écriture finale dans DMP_MLFeatures ────────────────────────────────
    const float ot = (cached_ot != DMP_OT_NOT_SET) ? cached_ot : OT_UNKNOWN;
    f.open_type      = ot;
    // 🆕 BUG #15 FIX: guard against invalid zone (0.0 after SC reset)
    f.open_zone      = (cached_oz >= 1.0f && cached_oz <= 7.0f) ? cached_oz : OZ_AT_POC;
    f.open_bias_conf = DMP_OT_Confidence(ot);
    f.open_direction = DMP_OT_Direction(ot);  // +1=bull / 0=neutre / -1=bear
    f.day_type       = cached_dt;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 11a — DIRECTION EXPLICITE (helper ML)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Extrait la direction du biais depuis open_type de manière lisible pour le ML.
//  Le ML préfère des features orthogonales : open_type (catégorielle) +
//  open_direction (ordinale -1/0/+1) donne deux signaux complémentaires.
//
//  Encodage :
//    +1.0  Biais haussier confirmé  : OD_UP(1) / OTD_UP(3) / ORR_UP(5) / OAOR_UP(8)
//     0.0  Neutre ou non résolu     : OAIR(7) / ODF_UP(10) / ODF_DOWN(11) / UNKNOWN(0)
//    -1.0  Biais baissier confirmé  : OD_DOWN(2) / OTD_DOWN(4) / ORR_DOWN(6) / OAOR_DOWN(9)
//
//  Note ODF : le drive a échoué → direction = 0 (signal ambigu, pas de biais net)

static inline float DMP_OT_Direction(float open_type) {
    const int v = (int)open_type;
    // Bullish : indices impairs (1,3,5) + 8 (OAOR_UP)
    if (v == 1 || v == 3 || v == 5 || v == 8) return +1.0f;
    // Bearish : indices pairs (2,4,6) + 9 (OAOR_DOWN)
    if (v == 2 || v == 4 || v == 6 || v == 9) return -1.0f;
    // Neutre   : OAIR(7), ODF_UP(10), ODF_DOWN(11), UNKNOWN(0)
    return 0.0f;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 11 — BIAS BOOST (utilitaire pour MIA_Layers.h)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Calcule le boost/malus de confiance d'un signal selon l'alignement
//  avec le biais d'ouverture détecté.
//
//  Utilisé dans Layer 1 de MIA pour pondérer les signaux.
//
//  direction : +1=long, -1=short
//  Retourne : float entre -0.30 et +0.20

static inline float DMP_OT_BiasBoost(int direction, float open_type) {
    const int ot = (int)open_type;
    const bool is_long  = (direction > 0);
    const bool is_short = (direction < 0);

    // Biais fortement bullish : OD_UP (1)
    // Biais bullish : OTD_UP (3), ORR_UP (5), OAOR_UP (8)
    // Biais fortement bearish : OD_DOWN (2)
    // Biais bearish : OTD_DOWN (4), ORR_DOWN (6), OAOR_DOWN (9)

    const bool strong_bull = (ot == 1);
    const bool bull        = (ot == 3 || ot == 5 || ot == 8);
    const bool strong_bear = (ot == 2);
    const bool bear        = (ot == 4 || ot == 6 || ot == 9);

    if (is_long) {
        if (strong_bull) return +0.20f;
        if (bull)        return +0.10f;
        if (strong_bear) return -0.30f;  // NE JAMAIS fader OD_DOWN
        if (bear)        return -0.15f;
    } else if (is_short) {
        if (strong_bear) return +0.20f;
        if (bear)        return +0.10f;
        if (strong_bull) return -0.30f;  // NE JAMAIS fader OD_UP
        if (bull)        return -0.15f;
    }

    return 0.0f; // OAIR, ODF, UNKNOWN : neutre (pas de biais clair)
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 12 — DIAGNOSTIC : DMP_LogOpenType()
// ═══════════════════════════════════════════════════════════════════════════════

inline void DMP_LogOpenType(SCStudyInterfaceRef sc, const DMP_MLFeatures& f) {
    static const char* zone_names[] = {
        "?", "<PDL", "VAL-PDL", "POC-VAL", "≈POC", "VAH-POC", "PDH-VAH", ">PDH"
    };
    static const char* dt_names[] = {
        "NonTrend", "Normal", "NormVar", "Neutral", "Trend"
    };
    const int oz = (std::min)(7, (std::max)(1, (int)f.open_zone));
    const int dt = (std::min)(4, (std::max)(0, (int)f.day_type));

    char msg[256];
    snprintf(msg, sizeof(msg),
        "[DMP_OpenType] zone=%s | type=%s(%.0f) | conf=%.2f | day=%s | r80=%.0f",
        zone_names[oz],
        DMP_OT_Name(f.open_type), f.open_type,
        f.open_bias_conf,
        dt_names[dt],
        f.rule_80pct);
    sc.AddMessageToLog(msg, 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_OpenType.h  —  v2.0
// ═══════════════════════════════════════════════════════════════════════════════
