#pragma once
// =============================================================================
// DMP_F12_BarShape.h  —  Batch B3 (F12) : Forme & taille de la bar 1min
// =============================================================================
//
//  Role : Exposer 10 features de morphologie de la bar courante :
//         corps (body), wicks, longueur normalisee ATR, patterns reversals
//         (shift -1), bar sans trade, range absolu.
//
//  Audit B3 2026-06-07 : 10 features GO PORT, 2 DROP (`range_h_minus_lprev_ticks`
//  + `range_hprev_minus_l_ticks` = LEAK_VOLATILITY ks_em>4, audit 28/04).
//  Cf DOCS/AUDIT_B3_F8_F9_F12_F22.md section F12.
//
//  Sources C++ deja disponibles :
//    * `r.price_close` / `r.price_open` / `r.price_high` / `r.price_low` :
//      BaseData OHLC natif Sierra Chart (sc.High/Low/Open/Close).
//    * `r.atr_14m` : ATR-14 intraday 1-min (TICKS) - lu par DMP_Calc_ATR_14m.
//    * `r.tick_size` : 0.25 ES/NQ - rempli par DMP_ReadAll.
//    * `r.fpbs_delta` : delta de la bar - lu par DMP_ReadFPBS.
//
//  Pendant Python :
//    * CORE/enricher_chain.py:740-758       (bar_body_pct/ticks)
//    * CORE/enricher_chain.py:1341-1364     (bar_upper_wick_pct/lower_wick_pct)
//    * CORE/phase_b_plus_engine.py:260-289  (long_up_bar / long_dn_bar — DEFER B3.B)
//    * CORE/phase_b_helpers.py:1275          (range_size)
//
//  B3.A deploy (2026-06-07 23:55) : SEULES les 5 SAFE features exposees au
//  JSONL : bar_body_pct, bar_body_ticks, bar_upper_wick_pct, bar_lower_wick_pct,
//  range_size. Les 5 unsafe (bar_no_trade, long_up_bar, long_dn_bar,
//  long_dn_up_pattern, long_up_dn_pattern) DEFER B3.B.
//
//  B3.B (session future) : Jackson 2026-06-07 23:58 — pas un refactor Python
//  mais un MAPPING vers les features Sierra NATIVES deja exposees dans le
//  JSONL (`bar_long_up_bar`, `bar_long_dn_bar`, `bar_long_dn_up`,
//  `bar_long_up_dn`, `dist_ext_long_up`, `dist_ext_long_dn` — Extension
//  Lines distances). Pattern Sierra-prime applique comme B2 (VWAP/VP/Session).
//  Seule `bar_no_trade` necessite refactor formule alignee Python `delta.isna()`
//  strict (pas d'equivalent Sierra natif).
//
//  Convention valeurs :
//    * bar_body_pct        : pourcentage signed [-100, 100], DMP_INVALID si range=0
//    * bar_body_ticks      : signed (positif = close > open), DMP_INVALID si tick_size=0
//    * bar_upper_wick_pct  : [0, 3] clamp (cf build_dataset_v4 ligne 809), DMP_INVALID si close=0
//    * bar_lower_wick_pct  : idem [0, 3]
//    * bar_no_trade        : 0 ou 1 boolean (DMP_INVALID si delta_bar inconnu impossible)
//    * long_up_bar         : 0 ou 1 boolean (close > open ET body > 2*ATR_points), DMP_INVALID si ATR null
//    * long_dn_bar         : 0 ou 1 boolean (close < open ET |body| > 2*ATR_points)
//    * long_dn_up_pattern  : 0 ou 1 (long_dn_bar[t-1] ET long_up_bar[t])
//    * long_up_dn_pattern  : 0 ou 1 (long_up_bar[t-1] ET long_dn_bar[t])
//    * range_size          : POINTS (high - low), DMP_INVALID si invalid amont
//
//  ATTENTION pattern 11 :
//    Le Sierra study `bar_long_up_bar` / `bar_long_dn_bar` (existant dans
//    DMP_RawData lignes 473-474) utilise une formule SC DIFFERENTE
//    (Edge Zones avec [-N] window). Ce helper implemente la formule
//    PYTHON `body > 2.0 * ATR_points` pour la parite. NE PAS reutiliser
//    `r.bar_long_up_bar` ici, c'est un autre signal (Sierra Edge Zone).
//
//  PersistVars (R3 review) :
//    * DMP_PERSIST_F12_PREV_LONG_UP  (205) : long_up_bar[t-1] persiste
//    * DMP_PERSIST_F12_PREV_LONG_DN  (206) : long_dn_bar[t-1] persiste
//
//  Ces 2 PersistVars sont stockes en float (0.0 ou 1.0). DMP_INVALID
//  (= FLT_MAX) au boot avant le 1er bar. Cas 1er bar : pattern = 0
//  par convention (pas de t-1 valide).
//
//  Date    : 2026-06-07
//  Build   : Batch B3 / Schema 3.7.20
// =============================================================================

#include "DMP_Reader.h"
#include <cmath>
#include <algorithm>          // std::max, std::min

// =============================================================================
// SECTION 1 — CONSTANTES
// =============================================================================

// Indices PersistVars pour patterns shift-1 (F12 long_dn_up / long_up_dn).
// 205-206 libres (scan exhaustif : 200-204 utilises par delta_div + B2 PDH/PDL).
constexpr int DMP_PERSIST_F12_PREV_LONG_UP = 205;
constexpr int DMP_PERSIST_F12_PREV_LONG_DN = 206;

// Seuil "longue bar" : body > N * ATR_points. Convention Python = 2.0.
// Reference : CORE/phase_b_plus_streaming.py:499 (add_phase_b_plus_long).
constexpr float DMP_F12_LONG_BAR_ATR_MULT = 2.0f;

// Wick clamp : cf CORE/build_dataset_v4_dmp_databento.py:809
// Empirique : 99% des wicks sont < 1.5%. Clamp 3.0 elimine les outliers
// tout en gardant le signal long-wick (rejet / hammer).
constexpr float DMP_F12_WICK_CLAMP_MAX = 3.0f;

// =============================================================================
// SECTION 2 — HELPERS
// =============================================================================

// Test "INVALID-like" sur un float (duplique DMP_WR_IsInvalid local).
static inline bool DMP_F12_IsInvalid(float v) {
    return (v >= FLT_MAX * 0.5f) || (v <= -FLT_MAX * 0.5f) || !std::isfinite(v);
}

// Test boolean "long_up_bar" type : body > seuil * ATR_points + sens.
// up=true -> require close > open ; up=false -> require close < open.
// ATR ici est en POINTS (atr_14m est en TICKS, conversion via tick_size).
static inline float DMP_F12_LongBar(
    float close, float open_val, float atr_points, bool want_up)
{
    if (!DMP_IsPriceValid(close) || !DMP_IsPriceValid(open_val))
        return DMP_INVALID;
    if (DMP_F12_IsInvalid(atr_points) || atr_points <= 0.0f)
        return DMP_INVALID;
    float body = close - open_val;
    float abs_body = (body >= 0.0f) ? body : -body;
    float threshold = DMP_F12_LONG_BAR_ATR_MULT * atr_points;
    bool sign_ok = want_up ? (body > 0.0f) : (body < 0.0f);
    bool size_ok = (abs_body > threshold);
    return (sign_ok && size_ok) ? 1.0f : 0.0f;
}

// =============================================================================
// SECTION 3 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 10 champs F12 dans DMP_MLFeatures.
//
// IMPORTANT : sc passe par reference pour acceder aux PersistVars. Doit etre
// appele 1 fois par bar (pour ne pas perturber l'etat shift-1).

inline void DMP_ComputeF12_BarShape(
    SCStudyInterfaceRef sc,
    DMP_MLFeatures& f,
    const DMP_RawData& r)
{
    // ─────────────────────────────────────────────────────────────────────────
    // PREP : valeurs sources + range bar + ATR points
    // ─────────────────────────────────────────────────────────────────────────
    const float close = r.price_close;
    const float open_val = r.price_open;
    const float high  = r.price_high;
    const float low   = r.price_low;
    const float tick  = (r.tick_size > 0.0f) ? r.tick_size : 0.25f;

    // Range en points (positive normalement). DMP_INVALID si OHLC casse.
    float range_points = DMP_INVALID;
    if (DMP_IsPriceValid(high) && DMP_IsPriceValid(low) && high >= low) {
        range_points = high - low;
    }

    // ATR_14m est en TICKS, convertir en POINTS (atr_points = atr_ticks * tick_size).
    // ATTENTION : c'est l'echelle ATR intraday 1min, pas atr_daily.
    float atr_points = DMP_INVALID;
    if (DMP_IsValid(r.atr_14m) && r.atr_14m > 0.0f) {
        atr_points = r.atr_14m * tick;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 1 — bar_body_pct : (close - open) / range * 100 (signed [-100, 100])
    // INVALID si range degenere (high == low, bar dot).
    // ─────────────────────────────────────────────────────────────────────────
    if (!DMP_IsPriceValid(close) || !DMP_IsPriceValid(open_val)
        || DMP_F12_IsInvalid(range_points) || range_points < 0.01f) {
        f.bar_body_pct = DMP_INVALID;
    } else {
        float body = close - open_val;
        float pct = (body / range_points) * 100.0f;
        // Clamp [-100, 100] : par construction body est dans [-range, +range]
        // mais on garde la garde anti-flotant.
        if (pct >  100.0f) pct =  100.0f;
        if (pct < -100.0f) pct = -100.0f;
        f.bar_body_pct = pct;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 2 — bar_body_ticks : (close - open) / tick_size (signed integer)
    // INVALID si OHLC casse ou tick_size invalide.
    // ─────────────────────────────────────────────────────────────────────────
    if (!DMP_IsPriceValid(close) || !DMP_IsPriceValid(open_val) || tick <= 0.0f) {
        f.bar_body_ticks = DMP_INVALID;
    } else {
        f.bar_body_ticks = (close - open_val) / tick;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 3 — bar_upper_wick_pct : (high - max(open, close)) / close * 100
    //   Clamp [0, DMP_F12_WICK_CLAMP_MAX] (=3.0).
    //   INVALID si close <= 0 ou OHLC casse.
    // ─────────────────────────────────────────────────────────────────────────
    if (!DMP_IsPriceValid(close) || close <= 0.0f
        || !DMP_IsPriceValid(open_val) || !DMP_IsPriceValid(high)) {
        f.bar_upper_wick_pct = DMP_INVALID;
    } else {
        float top_body = std::max(open_val, close);
        float wick = high - top_body;
        if (wick < 0.0f) wick = 0.0f;  // garde anti-flotant
        float pct = (wick / close) * 100.0f;
        if (pct > DMP_F12_WICK_CLAMP_MAX) pct = DMP_F12_WICK_CLAMP_MAX;
        f.bar_upper_wick_pct = pct;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 4 — bar_lower_wick_pct : (min(open, close) - low) / close * 100
    //   Clamp [0, 3.0]. INVALID si OHLC casse.
    // ─────────────────────────────────────────────────────────────────────────
    if (!DMP_IsPriceValid(close) || close <= 0.0f
        || !DMP_IsPriceValid(open_val) || !DMP_IsPriceValid(low)) {
        f.bar_lower_wick_pct = DMP_INVALID;
    } else {
        float bot_body = std::min(open_val, close);
        float wick = bot_body - low;
        if (wick < 0.0f) wick = 0.0f;
        float pct = (wick / close) * 100.0f;
        if (pct > DMP_F12_WICK_CLAMP_MAX) pct = DMP_F12_WICK_CLAMP_MAX;
        f.bar_lower_wick_pct = pct;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 5 — bar_no_trade : 1 si fpbs_delta == DMP_INVALID, 0 sinon
    //
    //   Formule REFACTORE 2026-06-08 00:30 (Jackson decision) :
    //   `delta_bar.isna()` Python STRICT (PAS `|delta|<0.5`).
    //   Equivalent C++ : DMP_F12_IsInvalid(r.fpbs_delta) only.
    //
    //   Verification empirique 9788 bars (5 jours NQ + 5 jours ES) :
    //     Python isna() = C++ refactor : 100% match (0 divergence)
    //     Python isna() = C++ ancien |d|<0.5 : 96.39% match (4% divergence)
    //   → refactor isna() strict est FIABLE A 100%.
    //
    //   Pendant Python : enricher_chain.py:1358-1364 et
    //                    build_dataset_v4_dmp_databento.py:1121.
    // ─────────────────────────────────────────────────────────────────────────
    f.bar_no_trade = DMP_F12_IsInvalid(r.fpbs_delta) ? 1.0f : 0.0f;

    // ═════════════════════════════════════════════════════════════════════════
    // FEATURES 6-9 NON-PORTEES — MAPPING SIERRA NATIVES B3.B (2026-06-08 00:30)
    //
    // Decision Jackson : utiliser les Sierra natives DEJA EXPOSEES dans le JSONL
    // au lieu de porter les formules Python (qui sont cassees) :
    //   long_up_bar Python (57.6% noise) → bar_long_up_bar Sierra (15.4% sain)
    //   long_dn_bar Python                → bar_long_dn_bar Sierra
    //   long_dn_up_pattern Python (lookahead leak) → bar_long_dn_up Sierra
    //   long_up_dn_pattern Python (lookahead leak) → bar_long_up_dn Sierra
    //   bonus distances : dist_ext_long_up / dist_ext_long_dn (Extension Lines)
    //
    // Pattern Sierra-prime applique (cf B2 VWAP/VP/Session). Aucune feature
    // ne sera ajoutee en B3.B cote C++ — uniquement documentation downstream.
    //
    // PersistVars 205-206 (DMP_PERSIST_F12_PREV_LONG_UP/DN) reservees mais
    // NON utilisees. Pas de cleanup necessaire (references inactives).
    // ═════════════════════════════════════════════════════════════════════════

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 10 — range_size : (high - low) en POINTS scalaire continu
    //   Note : ce N'EST PAS la meme chose que `range_size_ticks` du Volume Profile
    //   (qui mesure VAH - VAL). C'est juste high - low de la bar courante en POINTS.
    // ─────────────────────────────────────────────────────────────────────────
    f.range_size = range_points;
}

// =============================================================================
// FIN DMP_F12_BarShape.h
// =============================================================================
